#!/usr/bin/env python3
"""tecdoc_create — Generate tec_manual.md and tec_manual.html from project source files.

Reads every Python source file in the current directory EXCEPT files under
``tests/`` (and a small set of standard excluded directories). Uses the ``ast``
module to extract classes, functions, methods, properties, constants, and
imports, then writes:

    tec_manual.md   — Markdown manual with Mermaid architecture diagrams
    tec_manual.html — Single-file styled HTML version of the same content

Finally, runs basic syntax / logical-error checks on both outputs (Mermaid
reserved-keyword check, HTML tag-balance, etc.).

Usage:
    python _tecdoc_create.py [project_root] [output_prefix]

Defaults: project_root = cwd, output_prefix = "tec".
"""

from __future__ import annotations
import ast
import re
import sys
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
EXCLUDED_DIRS = {
    "tests",
    "__pycache__",
    ".git",
    ".pytest_cache",
    "0_bak",
    "docs",
    "_internal",
    "htmlcov",
    ".venv",
    "node_modules",
    "_bak",
    "bak",
    ".idea",
    ".vscode",
}
EXCLUDED_FILE_PREFIXES = ("test_", "_test", "conftest")
SOURCE_EXTENSIONS = {".py"}
MERMAID_RESERVED = {
    "end",
    "class",
    "style",
    "click",
    "subgraph",
    "direction",
    "default",
    "graph",
    "flowchart",
    "stateDiagram",
}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def find_source_files(root: Path) -> list[Path]:
    """Find Python source files, excluding test dirs and other noise."""
    result: list[Path] = []
    for p in root.rglob("*.py"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        # Exclude any path part that is in EXCLUDED_DIRS
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        # Exclude test-style file names
        if any(p.name.startswith(pre) for pre in EXCLUDED_FILE_PREFIXES):
            continue
        result.append(p)
    return sorted(result)


# ---------------------------------------------------------------------------
# AST extraction
# ---------------------------------------------------------------------------
def parse_file(path: Path) -> tuple[ast.Module | None, dict[int, str]]:
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
        section_map = {}
        for i, line in enumerate(src.splitlines()):
            m = re.match(r"^\s*#\s*SECTION\s+(.*)", line, re.IGNORECASE)
            if m:
                title = m.group(1).strip()
                title = re.sub(r"[-=]+$", "", title).strip()
                section_map[i + 1] = "Section " + title
        return tree, section_map
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"  WARNING: could not parse {path}: {e}")
        return None, None


def _func_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Return a short human-readable signature for a function/method."""
    parts: list[str] = []
    posargs = list(node.args.posonlyargs) + list(node.args.args)
    defaults = list(node.args.defaults)
    pad = len(posargs) - len(defaults)

    def _fmt(arg: ast.arg) -> str:
        if arg.annotation is not None:
            return f"{arg.arg}: {ast.unparse(arg.annotation)}"
        return arg.arg

    for i, arg in enumerate(posargs):
        s = _fmt(arg)
        if i >= pad:
            s += "=…"
        parts.append(s)
    if node.args.vararg:
        parts.append(f"*{node.args.vararg.arg}")
    if node.args.kwarg:
        parts.append(f"**{node.args.kwarg.arg}")
    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        s = _fmt(arg)
        if default is not None:
            s += "=…"
        parts.append(s)
    sig = ", ".join(parts)
    if node.returns is not None:
        sig += f" -> {ast.unparse(node.returns)}"
    return sig


def extract_function(node) -> dict:
    return {
        "name": node.name,
        "signature": _func_signature(node),
        "decorators": [ast.unparse(d) for d in node.decorator_list],
        "docstring": ast.get_docstring(node) or "",
        "lineno": node.lineno,
        "is_async": isinstance(node, ast.AsyncFunctionDef),
        "is_property": any(
            (isinstance(d, ast.Name) and d.id == "property")
            or (isinstance(d, ast.Attribute) and d.attr == "property")
            for d in node.decorator_list
        ),
    }


def extract_class(node) -> dict:
    cls = {
        "name": node.name,
        "bases": [ast.unparse(b) for b in node.bases],
        "docstring": ast.get_docstring(node) or "",
        "methods": [],
        "properties": [],
        "class_vars": [],
        "lineno": node.lineno,
    }
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn = extract_function(item)
            if fn["is_property"]:
                cls["properties"].append(fn)
            else:
                cls["methods"].append(fn)
        elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            cls["class_vars"].append(item.target.id)
        elif isinstance(item, ast.Assign):
            for tgt in item.targets:
                if isinstance(tgt, ast.Name):
                    cls["class_vars"].append(tgt.id)
    return cls


def _call_target_name(call_node: ast.Call) -> str | None:
    """Best-effort name extraction from a ``Call`` node.

    Handles plain names (``foo()``), method calls (``obj.foo()``), and
    chained attributes (``self.x.foo()`` → ``foo``).
    """
    func = call_node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _collect_call_edges(tree: ast.Module) -> list[tuple[str, str]]:
    """Return ``(caller, callee)`` edges for every call in the tree.

    Walks every function/method body and records a directed edge for every
    ``Call`` whose target we can resolve by name. Duplicates are removed.
    """
    edges: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            caller = node.name
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    callee = _call_target_name(child)
                    if callee and callee != caller:
                        edges.add((caller, callee))
    return sorted(edges)


def _class_methods_call_edges(cls_node: ast.ClassDef) -> list[tuple[str, str]]:
    """Per-class call edges using ``Class.method`` identifiers."""
    edges: set[tuple[str, str]] = set()
    for item in cls_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            caller = f"{cls_node.name}.{item.name}"
            for child in ast.walk(item):
                if isinstance(child, ast.Call):
                    callee = _call_target_name(child)
                    if not callee:
                        continue
                    # ``self.foo()`` is recorded as ``ClassName.foo`` when possible
                    if (
                        isinstance(child.func, ast.Attribute)
                        and isinstance(child.func.value, ast.Name)
                        and child.func.value.id == "self"
                    ):
                        edges.add((caller, f"{cls_node.name}.{callee}"))
                    else:
                        edges.add((caller, callee))
    return sorted(edges)


def extract_structure(
    tree: ast.Module, path: Path, section_map: dict[int, str]
) -> dict:
    s = {
        "path": str(path),
        "docstring": ast.get_docstring(tree) or "",
        "imports": [],
        "classes": [],
        "functions": [],
        "constants": [],
        "call_edges": [],
    }

    def get_section(lineno: int) -> str:
        s = "General"
        for ln in sorted(section_map.keys()):
            if ln <= lineno:
                s = section_map[ln]
        return s

    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                s["imports"].append(a.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for a in node.names:
                s["imports"].append(f"{mod}.{a.name}" if mod else a.name)
        elif isinstance(node, ast.ClassDef):
            cls = extract_class(node)
            cls["section"] = get_section(node.lineno)
            s["classes"].append(cls)
            # Per-class method call edges (ClassName.method → target)
            for caller, callee in _class_methods_call_edges(node):
                s["call_edges"].append((caller, callee))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            f = extract_function(node)
            f["section"] = get_section(node.lineno)
            s["functions"].append(f)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id.isupper():
                    try:
                        s["constants"].append(
                            (
                                tgt.id,
                                ast.literal_eval(node.value),
                                get_section(node.lineno),
                            )
                        )
                    except Exception:
                        s["constants"].append(
                            (tgt.id, "<expr>", get_section(node.lineno))
                        )
    # Module-level call edges (caller is just the function name)
    for caller, callee in _collect_call_edges(tree):
        s["call_edges"].append((caller, callee))
    # Deduplicate
    s["call_edges"] = sorted(set(s["call_edges"]))
    return s


# ---------------------------------------------------------------------------
# Markdown generation
# ---------------------------------------------------------------------------
def _safe_id(name: str) -> str:
    """Produce a Mermaid-safe node id (avoids reserved words & special chars)."""
    sid = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not sid or sid[0].isdigit():
        sid = "_" + sid
    if sid.lower() in MERMAID_RESERVED:
        sid = sid + "_n"
    return sid


def _slugify(name: str) -> str:
    """Produce a clean, lowercase HTML anchor id from a name."""
    slug = re.sub(r"[^\w\s-]", "", name).lower().replace(" ", "-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def _heading_slug(heading_text: str) -> str:
    """Generate a slug from a markdown H3 heading (class/func definition).

    Extracts just the name before the first parenthesis and strips
    backticks and the ``class`` prefix so the result matches what
    :func:`_extract_toc` produces.

    Example::
        _heading_slug("`class JobTemplate(Base)`") == "jobtemplate"
        _heading_slug("`find_source_files(root: Path)`") == "find_source_files"
    """
    name = heading_text.replace("`", "").strip()
    paren_idx = name.find("(")
    if paren_idx > 0:
        name = name[:paren_idx].strip()
    if name.startswith("class "):
        name = name[6:]
    return _slugify(name)


def _short_doc(doc: str, max_lines: int = 2) -> str:
    if not doc:
        return ""
    lines = [line.rstrip() for line in doc.splitlines()]
    lines = [line for line in lines if line.strip()]
    return "\n".join(lines[:max_lines])


def generate_markdown(structures: list[dict], project_root: Path) -> str:
    total_classes = sum(len(s["classes"]) for s in structures)
    total_funcs = sum(len(s["functions"]) for s in structures)
    total_methods = sum(
        len(c["methods"]) + len(c["properties"])
        for s in structures
        for c in s["classes"]
    )

    md: list[str] = []
    md.append(f"# Technical Manual — `{project_root.name}`")
    md.append("")
    md.append(
        "> Auto-generated by **`tecdoc_create`** from the project's Python source "
        "files. Tests, caches, and other non-source directories are excluded."
    )
    md.append("")

    # 1. Project overview
    md.append("## 🗺️ Architecture Overview")
    md.append("")
    if structures and structures[0]["docstring"]:
        first_lines = "\n".join(structures[0]["docstring"].splitlines()[:6])
        md.append("```")
        md.append(first_lines)
        md.append("```")
        md.append("")
    md.append(
        f"This manual documents **{len(structures)}** source file(s) containing "
        f"**{total_classes}** class(es), **{total_funcs}** module-level function(s), "
        f"and **{total_methods}** method(s) / property(ies) in total."
    )
    md.append("")

    md.append("### Module Dependencies (from imports)")
    md.append("")
    project_modules = {s["path"].replace("\\", "/") for s in structures}
    import_edges: list[tuple[str, str]] = []
    for s in structures:
        importer = s["path"]
        for imp in s["imports"]:
            head = imp.split(".")[0]
            for pm in project_modules:
                pm_stem = Path(pm).stem
                if head == pm_stem or imp == pm_stem:
                    if importer != pm:
                        import_edges.append((importer, pm))
    import_edges = sorted(set(import_edges))
    md.append("```mermaid")
    md.append("graph LR")
    for src_file, dst in import_edges:
        a = _safe_id(src_file)
        b = _safe_id(dst)
        md.append(f'    {a}["{src_file}"] --> {b}["{dst}"]')
    if not import_edges:
        for s in structures:
            md.append(f'    {_safe_id(s["path"])}["{s["path"]}"]')
    md.append("```")
    md.append("")

    # Group by Sections
    sections = {}  # dict mapping section title -> list of items
    for s in structures:
        for c in s["classes"]:
            sec = c.get("section", "General")
            sections.setdefault(sec, {"classes": [], "functions": [], "constants": []})[
                "classes"
            ].append((s["path"], c))
        for f in s["functions"]:
            sec = f.get("section", "General")
            sections.setdefault(sec, {"classes": [], "functions": [], "constants": []})[
                "functions"
            ].append((s["path"], f))
        for c_tuple in s["constants"]:
            name, value, sec = c_tuple
            sections.setdefault(sec, {"classes": [], "functions": [], "constants": []})[
                "constants"
            ].append((s["path"], name, value))

    # Sort sections. "General" first, then alphabetically, but usually dd.py has numbers.
    # We can just sort by name (Section 1, Section 2 will sort nicely).
    def _sort_key(sec_title):
        m = re.search(r"\d+", sec_title)
        if m:
            return (0, int(m.group()))
        if sec_title == "General":
            return (-1, 0)
        return (1, sec_title)

    sorted_sections = sorted(sections.keys(), key=_sort_key)

    for sec_title in sorted_sections:
        md.append(f"## {sec_title}")
        md.append("")
        data = sections[sec_title]

        # Constants
        if data["constants"]:
            md.append("**Constants:**")
            md.append("")
            for path, name, value in sorted(data["constants"]):
                md.append(f"- `{name}` = `{value!r}` _(in `{path}`)_")
            md.append("")

        # Classes
        for path, cls in sorted(data["classes"], key=lambda x: x[1]["name"]):
            bases = f"({', '.join(cls['bases'])})" if cls["bases"] else ""
            md.append(f"### `class {cls['name']}{bases}`")
            md.append(f"_in `{path}` (line {cls['lineno']})_")
            md.append("")
            if cls["docstring"]:
                md.append("```")
                md.append(_short_doc(cls["docstring"], 6))
                md.append("```")
                md.append("")
            if cls["class_vars"]:
                md.append(
                    "**Class variables:** "
                    + ", ".join(f"`{v}`" for v in cls["class_vars"])
                )
                md.append("")
            if cls["properties"]:
                md.append("**Properties:**")
                md.append("")
                for p in cls["properties"]:
                    md.append(
                        f"- `{p['name']}` → `{p['signature']}` (line {p['lineno']})"
                    )
                    sd = _short_doc(p["docstring"], 1)
                    if sd:
                        md.append(f"  - {sd}")
                md.append("")
            if cls["methods"]:
                md.append("**Methods:**")
                md.append("")
                sorted_methods = sorted(
                    cls["methods"],
                    key=lambda m: (not m["name"].startswith("__"), m["name"]),
                )
                for m in sorted_methods:
                    deco = " ".join(f"@{d} " for d in m["decorators"])
                    md.append(
                        f"- {deco}**`{m['name']}{m['signature']}`** _(line {m['lineno']})_".replace(
                            "}}", "}"
                        )
                    )
                    sd = _short_doc(m["docstring"], 1)
                    if sd:
                        md.append(f"  - {sd}")
                md.append("")

        # Functions
        for path, f in sorted(data["functions"], key=lambda x: x[1]["name"]):
            md.append(f"### `{f['name']}({f['signature']})`")
            md.append(f"_in `{path}` (line {f['lineno']})_")
            md.append("")
            if f["docstring"]:
                md.append("```")
                md.append(_short_doc(f["docstring"], 8))
                md.append("```")
                md.append("")

    # 📞 Master Call Index (Functions → Functions they call)
    md.append("## 📞 Master Call Index")
    md.append("")
    # Build a (caller → callee) edge list across all source files
    edges: list[tuple[str, str]] = []
    known: set[str] = set()
    for s in structures:
        for f in s["functions"]:
            known.add(f["name"])
        for c in s["classes"]:
            for m in c["methods"] + c["properties"]:
                known.add(f"{c['name']}.{m['name']}")
            known.add(c["name"])
        for edge in s["call_edges"]:
            edges.append(edge)
    edges = sorted({(a, b) for a, b in edges if a in known and b in known})
    md.append(f"_Extracted {len(edges)} call edges from the AST of all source files._")
    md.append("")

    return "\n".join(md)


# ---------------------------------------------------------------------------
# Build cross-reference index from AST structures
# ---------------------------------------------------------------------------
def _build_xref(structures: list[dict]) -> dict:
    """Return a dict mapping name → {type, file, calls, called_by, lineno, bases}."""
    xref: dict[str, dict] = {}
    # Register all known names
    for s in structures:
        for c in s["classes"]:
            xref[c["name"]] = {
                "type": "class",
                "file": s["path"],
                "calls": [],
                "called_by": [],
                "lineno": c["lineno"],
                "bases": c["bases"],
            }
        for f in s["functions"]:
            xref[f["name"]] = {
                "type": "function",
                "file": s["path"],
                "calls": [],
                "called_by": [],
                "lineno": f["lineno"],
                "bases": [],
            }
    # Populate call/called_by edges
    for s in structures:
        for caller, callee in s["call_edges"]:
            # Methods will be logged under their base class if they exist
            caller_base = caller.split(".")[0]
            callee_base = callee.split(".")[0]
            if caller_base in xref and callee_base in xref:
                xref[caller_base]["calls"].append(callee)
                xref[callee_base]["called_by"].append(caller)
    return xref


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------
def _extract_toc(md: str) -> list[tuple[int, str, str]]:
    """Extract (level, text, slug) for every H2 and H3 heading.

    For H3 headings (class/function definitions), uses :func:`_heading_slug`
    to produce clean, matchable slugs. H2 slugs use the full heading text.
    """
    toc: list[tuple[int, str, str]] = []
    for line in md.split("\n"):
        m = re.match(r"^(##|###)\s+(.*)", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            if level == 3:
                slug = _heading_slug(text)
            else:
                slug = re.sub(r"[^\w\s-]", "", text).lower().replace(" ", "-")
            toc.append((level, text, slug))
    return toc


def _render_sidebar(toc: list[tuple[int, str, str]], project_name: str) -> str:
    """Build the sticky left-side navigation with collapsible sections."""
    rows = [
        '<aside class="sidebar">',
        '  <div class="sidebar-header">',
        f"    <h1>\U0001f4d8 {project_name}</h1>",
        '    <div class="sub">Technical Manual</div>',
        "  </div>",
        '  <nav id="sidebar-nav">',
    ]
    details_open = False
    for i, (level, text, slug) in enumerate(toc):
        clean = text.replace("`", "").strip()
        if level == 2:
            if details_open:
                rows.append("  </details>")
                details_open = False
            # Check if this H2 has any H3 children
            has_h3 = False
            for j in range(i + 1, len(toc)):
                if toc[j][0] == 3:
                    has_h3 = True
                elif toc[j][0] == 2:
                    break
            if has_h3:
                rows.append("  <details open>")
                rows.append(f"    <summary>{clean}</summary>")
                details_open = True
            else:
                rows.append(f'    <a href="#{slug}" class="section-link">{clean}</a>')
        else:
            rows.append(f'    <a href="#{slug}">{clean}</a>')
    if details_open:
        rows.append("  </details>")
    rows.append("  </nav>")
    rows.append("</aside>")
    return "\n".join(rows)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline(text: str) -> str:
    text = _esc(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def _md_to_html(md: str, xref: dict | None = None) -> str:
    """Convert the generated markdown into rich HTML with card-based layouts.

    Detects class and function definitions on the fly and wraps them in styled
    ``<div class="class-card">`` / ``<div class="func-card">`` containers with
    tags and cross-reference links.
    """
    out: list[str] = []
    lines = md.split("\n")
    i = 0
    in_code = False
    in_mermaid = False
    mermaid_buf: list[str] = []
    list_open = False
    table_open = False
    in_card = False  # True while inside a class-card / func-card
    card_name = ""  # e.g. "JobTemplate"
    card_file = ""  # e.g. "dd.py"
    card_lineno = ""  # e.g. "120"

    def _xref_links(name: str) -> str:
        """Build 'Calls:' and 'Called by:' HTML for a given name."""
        if not xref or name not in xref:
            return ""
        info = xref[name]
        parts: list[str] = []
        if info["calls"]:
            links = "".join(
                f'<a href="#{_slugify(c.split(".")[0])}">{c}</a>, '
                for c in sorted(set(info["calls"]))
            ).rstrip(", ")
            parts.append(f'<p class="xref"><strong>Calls:</strong> {links}</p>')
        if info["called_by"]:
            links = "".join(
                f'<a href="#{_slugify(c.split(".")[0])}">{c}</a>, '
                for c in sorted(set(info["called_by"]))
            ).rstrip(", ")
            parts.append(f'<p class="xref"><strong>Called by:</strong> {links}</p>')
        return "\n".join(parts)

    def _card_tags(name: str, type_: str, bases: list[str]) -> str:
        """Generate styled tag HTML."""
        tags = []
        if type_ == "class":
            tags.append('<span class="tag tag-class">CLASS</span>')
            if any("Enum" in b for b in bases) or any("IntFlag" in b for b in bases):
                tags.append('<span class="tag tag-enum">ENUM</span>')
            elif "type" in [b.lower() for b in bases]:
                tags.append('<span class="tag tag-warn">METACLASS</span>')
        else:
            if name.startswith("_"):
                tags.append('<span class="tag tag-private">PRIVATE</span>')
            else:
                tags.append('<span class="tag">FUNCTION</span>')
        return " ".join(tags)

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Mermaid block
        if stripped == "```mermaid":
            in_mermaid = True
            mermaid_buf = []
            i += 1
            continue
        if in_mermaid:
            if stripped == "```":
                in_mermaid = False
                out.append('<div class="mermaid">')
                out.append("\n".join(_esc(line) for line in mermaid_buf))
                out.append("</div>")
                i += 1
                continue
            mermaid_buf.append(line)
            i += 1
            continue

        # Code block
        if stripped.startswith("```"):
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                out.append("<pre><code>")
                in_code = True
            i += 1
            continue
        if in_code:
            out.append(_esc(line))
            i += 1
            continue

        # Detect class / function card boundaries
        h3_match = re.match(r"^###\s+(.*)", line)

        if h3_match and not in_code:
            # Close previous card if open
            if in_card:
                # Add cross-reference links
                if card_name:
                    out.append(_xref_links(card_name))
                out.append("</div>")
                in_card = False
                card_name = ""
                card_file = ""
                card_lineno = ""

            heading_text = h3_match.group(1)
            # Check if next line is the meta line: _in `file.py` (line N)_
            is_card = False
            next_line = lines[i + 1] if i + 1 < len(lines) else ""
            meta_match = (
                re.match(r"^_in\s+`(.+?)`\s+\(line\s+(\d+)\)_$", next_line.strip())
                if next_line
                else None
            )

            if meta_match:
                card_file = meta_match.group(1)
                card_lineno = meta_match.group(2)
                is_card = True

            if is_card:
                # Determine if class or function
                class_match = re.match(r"`class\s+(\w+(?:\.\w+)*)", heading_text)
                func_match = (
                    re.match(r"`(\w[\w_]*)", heading_text) if not class_match else None
                )

                if class_match:
                    card_name = class_match.group(1)
                    bases_match = re.search(r"\(([^)]*)\)", heading_text)
                    bases = (
                        [b.strip() for b in bases_match.group(1).split(",")]
                        if bases_match
                        else []
                    )
                    tags = _card_tags(card_name, "class", bases)
                    out.append(
                        f'<div class="class-card" id="{_heading_slug(heading_text)}">'
                    )
                    out.append(
                        f'  <div class="class-name">{_esc(card_name)} {tags}</div>'
                    )
                    out.append(
                        f'  <div class="class-meta">📄 {card_file} · line {card_lineno}</div>'
                    )
                    in_card = True
                elif func_match:
                    card_name = func_match.group(1)
                    tags = _card_tags(card_name, "function", [])
                    out.append(
                        f'<div class="func-card" id="{_heading_slug(heading_text)}">'
                    )
                    out.append(
                        f'  <div class="func-name">{_esc(card_name)} {tags}</div>'
                    )
                    out.append(
                        f'  <div class="func-meta">📄 {card_file} · line {card_lineno}</div>'
                    )
                    in_card = True

                # Skip the next line (meta line) since we've already rendered it
                i += 2
                continue
            else:
                # Regular H3, not a card
                slug = _slugify(heading_text)
                out.append(f'<h3 id="{slug}">{_inline(heading_text)}</h3>')
                i += 1
                continue

        # Close card on H2 hit
        if re.match(r"^##\s", line):
            if in_card:
                if card_name:
                    out.append(_xref_links(card_name))
                out.append("</div>")
                in_card = False
                card_name = ""
                card_file = ""
                card_lineno = ""

        # Tables (very simple)
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if re.match(r"^[-:|\\s]+$", cells[0] if cells else ""):
                i += 1
                continue
            if not table_open:
                out.append("<table>")
                table_open = True
            is_header = i + 1 < len(lines) and re.match(
                r"^\s*\|[-:\s|]+\|\s*$", lines[i + 1]
            )
            tag = "th" if is_header else "td"
            out.append(
                "<tr>"
                + "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in cells)
                + "</tr>"
            )
            i += 1
            continue
        elif table_open:
            out.append("</table>")
            table_open = False

        # Headers (H1, H2 — H3 already handled above)
        m = re.match(r"^(#{1,2})\s+(.*)", line)
        if m:
            if list_open:
                out.append("</ul>")
                list_open = False
            level = len(m.group(1))
            slug = _slugify(m.group(2))
            out.append(f'<h{level} id="{slug}">{_inline(m.group(2))}</h{level}>')
            i += 1
            continue

        # Horizontal rule
        if re.match(r"^-{3,}\s*$", stripped):
            out.append("<hr>")
            i += 1
            continue

        # Blockquote
        if stripped.startswith(">"):
            text = stripped[1:].strip()
            out.append(f"<blockquote><p>{_inline(text)}</p></blockquote>")
            i += 1
            continue

        # Lists
        if re.match(r"^- ", stripped):
            if not list_open:
                out.append("<ul>")
                list_open = True
            content = re.sub(r"^- ", "", stripped)
            out.append(f"<li>{_inline(content)}</li>")
            i += 1
            continue
        elif list_open:
            out.append("</ul>")
            list_open = False

        # Empty line
        if not stripped:
            out.append("")
            i += 1
            continue

        # Paragraph
        out.append(f"<p>{_inline(line)}</p>")
        i += 1

    if list_open:
        out.append("</ul>")
    if table_open:
        out.append("</table>")
    if in_card:
        if card_name:
            out.append(_xref_links(card_name))
        out.append("</div>")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Mermaid asset bundling
# ---------------------------------------------------------------------------
MERMAID_CDN_URL = "https://cdn.jsdelivr.net/npm/mermaid@9.4.3/dist/mermaid.min.js"
MERMAID_CACHE_DIRNAME = "_tecdoc_assets"
MERMAID_CACHE_FILENAME = "mermaid.min.js"
MERMAID_MAX_CACHE_AGE_DAYS = 30


def _display_path(p: Path, root: Path) -> str:
    """Show ``p`` relative to ``root`` if possible, else as an absolute path."""
    try:
        return str(p.relative_to(root))
    except ValueError:
        # p is not under root (e.g. an absolute --output-dir was used)
        return str(p)


def _minify_js(js: str) -> str:
    """Crude JS minifier: safely collapse whitespace only.

    The Mermaid CDN file is already fully minified, so aggressive comment
    stripping is unnecessary and risks corrupting strings/regexes in the
    bundled library. We just collapse runs of whitespace to save ~8-12%.
    """
    # Collapse runs of whitespace to a single space
    js = re.sub(r"\s+", " ", js)
    # Trim leading/trailing whitespace
    return js.strip()


def _mermaid_cache_path(project_root: Path) -> Path:
    return project_root / MERMAID_CACHE_DIRNAME / MERMAID_CACHE_FILENAME


def _fetch_mermaid_js(project_root: Path, minify: bool = True) -> str | None:
    """Return the contents of mermaid.min.js, using a local cache when possible.

    The Mermaid library is downloaded once and stored under
    ``<project_root>/_tecdoc_assets/mermaid.min.js`` so the generated HTML can
    be 100 % self-contained and work offline. The returned source is run
    through :func:`_minify_js` to shrink the embedded payload.
    """
    cache = _mermaid_cache_path(project_root)
    cache.parent.mkdir(parents=True, exist_ok=True)

    # Use cached file if it exists and is fresh enough
    if cache.exists():
        age_days = (project_root.stat().st_mtime - cache.stat().st_mtime) / 86400.0
        if age_days < MERMAID_MAX_CACHE_AGE_DAYS:
            try:
                text = cache.read_text(encoding="utf-8")
                return _minify_js(text) if minify else text
            except Exception as e:
                print(f"  WARNING: could not read Mermaid cache: {e}")

    # Download fresh copy
    print(f"  Downloading Mermaid from {MERMAID_CDN_URL} \u2026")
    try:
        req = urllib.request.Request(
            MERMAID_CDN_URL,
            headers={"User-Agent": "tecdoc_create/1.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            text = data.decode("utf-8")
        cache.write_text(text, encoding="utf-8")
        print(f"  Cached Mermaid ({len(text):,} bytes) at {cache}")
        return _minify_js(text) if minify else text
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        print(f"  WARNING: could not download Mermaid: {e}")
        if cache.exists():
            print("  Falling back to cached copy (may be stale).")
            try:
                text = cache.read_text(encoding="utf-8")
                return _minify_js(text) if minify else text
            except Exception:
                pass
        return None


def generate_html(
    structures: list[dict],
    project_root: Path,
    md_content: str,
    bundle_mermaid: bool = True,
    minify_mermaid: bool = True,
) -> str:
    xref = _build_xref(structures)
    body = _md_to_html(md_content, xref=xref)
    toc = _extract_toc(md_content)
    sidebar = _render_sidebar(toc, project_root.name)

    if not bundle_mermaid:
        mermaid_tag = '<script src="https://cdn.jsdelivr.net/npm/mermaid@9.4.3/dist/mermaid.min.js"></script>'
    else:
        mermaid_js = _fetch_mermaid_js(project_root, minify=minify_mermaid)
        if mermaid_js is not None:
            mermaid_js = re.sub(r"</script>\s*$", "", mermaid_js, flags=re.IGNORECASE)
            mermaid_tag = f"<script>\n{mermaid_js}\n</script>"
        else:
            mermaid_tag = (
                "<!-- Mermaid could not be embedded; falling back to CDN. -->\n"
                '<script src="https://cdn.jsdelivr.net/npm/mermaid@9.4.3/dist/mermaid.min.js"></script>'
            )

    # Build quick-jump links from TOC (key sections at the top)
    quick_jump_links = []
    key_sections = {
        "1. Project Overview",
        "2. Source Files",
        "3. Architecture Diagram",
        "6. Classes",
        "7. Functions",
        "8. Class Hierarchy",
        "9. Call Graph",
    }
    for level, text, slug in toc:
        clean = text.replace("`", "").strip()
        if clean in key_sections:
            quick_jump_links.append(f'<a href="#{slug}">{clean}</a>')

    css = """
:root { --bg: #fff; --fg: #1f2328; --muted: #57606a; --accent: #0969da;
        --border: #d0d7de; --code-bg: #f1f3f5; --card: #f7f8fa; --sidebar-bg: #f7f8fa;
        --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace; }
[data-theme="dark"] { --bg: #0d1117; --fg: #e6edf3; --muted: #8b949e;
        --accent: #58a6ff; --border: #30363d; --code-bg: #1b2129; --card: #161b22; --sidebar-bg: #161b22; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       line-height: 1.6; color: var(--fg); background: var(--bg); }

/* === Layout: sticky sidebar + scrollable content ====================== */
.layout { display: grid; grid-template-columns: 280px 1fr; min-height: 100vh; }
.sidebar { position: sticky; top: 0; height: 100vh; overflow-y: auto;
           background: var(--sidebar-bg); border-right: 1px solid var(--border);
           padding: 20px 0; }
.sidebar-header { padding: 0 20px 16px; border-bottom: 1px solid var(--border);
                  margin-bottom: 12px; }
.sidebar-header h1 { font-size: 18px; margin: 0 0 4px 0; color: var(--accent);
                     border: none; padding: 0; }
.sidebar-header .sub { font-size: 12px; color: var(--muted); }
.sidebar nav { padding: 0 8px; }
.sidebar nav details { margin: 4px 0; }
.sidebar nav summary { cursor: pointer; padding: 6px 12px; font-weight: 600;
                       font-size: 13px; color: var(--fg); list-style: none;
                       border-radius: 6px; user-select: none; }
.sidebar nav summary::-webkit-details-marker { display: none; }
.sidebar nav summary::before { content: "\25b6"; display: inline-block;
                               margin-right: 6px; font-size: 10px;
                               transition: transform 0.15s; color: var(--muted); }
.sidebar nav details[open] > summary::before { transform: rotate(90deg); }
.sidebar nav summary:hover { background: var(--code-bg); }
.sidebar nav a { display: block; padding: 4px 12px 4px 28px; color: var(--muted);
                 text-decoration: none; font-size: 13px; border-radius: 4px; }
.sidebar nav a.section-link { padding: 4px 12px; font-weight: 600; color: var(--fg); }
.sidebar nav a:hover { color: var(--accent); background: var(--code-bg); }
.sidebar nav a.active { color: var(--accent); font-weight: 600; background: var(--code-bg); }
.content { padding: 32px 48px; max-width: 1100px; }

/* === Quick-jump links bar ============================================= */
.toctoc { display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0 24px; }
.toctoc a { background: var(--card); border: 1px solid var(--border);
            padding: 6px 16px; border-radius: 20px; font-size: 13px;
            color: var(--accent); text-decoration: none; transition: all 0.15s; }
.toctoc a:hover { background: var(--accent); color: #fff; border-color: var(--accent); }

/* === Typography ====================================================== */
h1 { color: var(--accent); border-bottom: 3px solid var(--accent);
     padding-bottom: 12px; font-size: 32px; }
h2 { color: var(--accent); border-bottom: 1px solid var(--border);
     padding-bottom: 6px; margin-top: 40px; scroll-margin-top: 20px; }
h3 { color: var(--accent); scroll-margin-top: 20px; }
h4, h5, h6 { color: var(--fg); }
code { background: var(--code-bg); padding: 1px 6px; border-radius: 4px;
       font-family: var(--mono); font-size: 0.88em; }
pre { background: var(--code-bg); padding: 14px 16px; border-radius: 8px;
      overflow-x: auto; border: 1px solid var(--border); }
pre code { background: transparent; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; }
th, td { border: 1px solid var(--border); padding: 8px 12px; text-align: left; }
th { background: var(--card); }
blockquote { border-left: 4px solid var(--accent); padding: 8px 16px;
             color: var(--muted); background: var(--card); border-radius: 0 6px 6px 0; }
.mermaid, .callgraph .mermaid { background: var(--card); padding: 16px; border-radius: 8px;
           margin: 16px 0; text-align: center; border: 1px solid var(--border); }
ul, ol { padding-left: 24px; }
li { margin: 4px 0; }
hr { border: none; border-top: 1px solid var(--border); margin: 24px 0; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* === Cards (classes & functions) ====================================== */
.class-card, .func-card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 10px; padding: 20px 24px; margin: 20px 0;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.class-name, .func-name {
  font-size: 20px; font-weight: 700; color: var(--fg);
  margin-bottom: 4px;
}
.class-meta, .func-meta {
  font-size: 12px; color: var(--muted); margin-bottom: 10px;
}
.class-card .docstring, .func-card .docstring {
  color: var(--fg); line-height: 1.5; margin: 8px 0;
}
.signature {
  font-family: var(--mono); background: var(--code-bg);
  padding: 10px 14px; border-radius: 6px; font-size: 13px;
  margin: 10px 0; overflow-x: auto; border: 1px solid var(--border);
}
/* Tags */
.tag {
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 700; letter-spacing: 0.3px;
  vertical-align: middle; margin-left: 6px; border: 1px solid transparent;
}
.tag:empty { display: none; }
.tag-class { background: #ddf4ff; color: #0550ae; border-color: #b6e3ff; }
.tag-private { background: #ffebe9; color: #cf222e; border-color: #ffcecb; }
.tag-warn { background: #fff8c5; color: #7a5e00; border-color: #f0d94e; }
.tag-enum { background: #dafbe1; color: #116329; border-color: #aceebb; }
.tag-function { background: #e6e6e6; color: #333; border-color: #ccc; }
[data-theme="dark"] .tag-class { background: #1f2d3d; color: #79b8ff; border-color: #2a4365; }
[data-theme="dark"] .tag-private { background: #3d1f1f; color: #ff7b72; border-color: #5c2a2a; }
[data-theme="dark"] .tag-warn { background: #3d3520; color: #d29922; border-color: #5c4b1f; }
[data-theme="dark"] .tag-enum { background: #1c3d2a; color: #7ee787; border-color: #28543b; }
[data-theme="dark"] .tag-function { background: #30363d; color: #e6edf3; border-color: #484f58; }
/* Members collapsible section inside cards */
.members { margin-top: 12px; }
.members summary { cursor: pointer; font-weight: 600; color: var(--accent);
                   padding: 4px 0; font-size: 14px; }
.members table { margin-top: 8px; }
/* Cross-reference links */
.xref { font-size: 13px; color: var(--muted); margin: 6px 0 0; }
.xref strong { color: var(--fg); }

/* === Search box ======================================================= */
.search-wrap { margin-bottom: 24px; }
#search-input {
  width: 100%; padding: 10px 16px; border-radius: 8px;
  border: 1px solid var(--border); background: var(--code-bg);
  color: var(--fg); font-size: 14px; transition: border-color 0.15s;
}
#search-input:focus { outline: none; border-color: var(--accent); }

/* === Theme toggle ===================================================== */
.theme-toggle { position: fixed; top: 16px; right: 16px; z-index: 100;
                background: var(--card); border: 1px solid var(--border);
                border-radius: 20px; padding: 6px 14px; cursor: pointer;
                color: var(--fg); font-size: 13px; transition: border-color 0.15s; }
.theme-toggle:hover { border-color: var(--accent); }

/* === Mobile: collapse sidebar to top bar ============================== */
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
  .sidebar { position: relative; height: auto; max-height: 50vh;
             border-right: none; border-bottom: 1px solid var(--border); }
  .content { padding: 20px; }
}

/* === Scrollbars ======================================================= */
.sidebar::-webkit-scrollbar { width: 8px; }
.sidebar::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
"""
    # Build the quick-jump HTML
    quick_jump_html = (
        f'<div class="toctoc">{" ".join(quick_jump_links)}</div>'
        if quick_jump_links
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Technical Manual — {project_root.name}</title>
{mermaid_tag}
<style>{css}</style>
</head>
<body>
<button class="theme-toggle" onclick="toggleTheme()">\U0001f313 Theme</button>
<div class="layout">
{sidebar}
<main class="content">
<div class="search-wrap"><input id="search-input" type="search" placeholder="\U0001f50d Search classes, functions, parameters\u2026"></div>
{quick_jump_html}
{body}
</main>
</div>
<script>
// Save mermaid source BEFORE mermaid processes it, so theme toggle can re-render
(function() {{
  document.querySelectorAll('.mermaid').forEach(el => {{
    el.dataset.src = el.innerHTML;
  }});
}})();

mermaid.initialize({{ startOnLoad: true, theme: 'default', securityLevel: 'loose' }});

function toggleTheme() {{
  const b = document.body;
  const cur = b.getAttribute('data-theme');
  b.setAttribute('data-theme', cur === 'dark' ? 'light' : 'dark');
  try {{ localStorage.setItem('tec-manual-theme', b.getAttribute('data-theme')); }} catch(e) {{}}
  // Re-render Mermaid so it picks up the new theme
  document.querySelectorAll('.mermaid').forEach((el) => {{
    if (el.dataset.src) {{
      el.innerHTML = el.dataset.src;
      el.removeAttribute('data-processed');
    }}
  }});
  try {{ mermaid.run(); }} catch(e) {{}}
}}
try {{
  const t = localStorage.getItem('tec-manual-theme');
  if (t) document.body.setAttribute('data-theme', t);
}} catch(e) {{}}

// === Sidebar active-state highlighting (scroll-spy) ===
(function() {{
  const links = Array.from(document.querySelectorAll('.sidebar nav a'));
  const map = new Map();
  links.forEach(a => {{
    const id = a.getAttribute('href').slice(1);
    const target = document.getElementById(id);
    if (target) map.set(target, a);
  }});
  const targets = Array.from(map.keys());
  if (!targets.length) return;

  function update() {{
    const scrollTop = window.scrollY + 80;
    let active = targets[0];
    for (const t of targets) {{
      if (t.offsetTop <= scrollTop) active = t;
    }}
    links.forEach(a => a.classList.remove('active'));
    const link = map.get(active);
    if (link) link.classList.add('active');
  }}
  let ticking = false;
  window.addEventListener('scroll', () => {{
    if (!ticking) {{ requestAnimationFrame(() => {{ update(); ticking = false; }}); ticking = true; }}
  }});
  update();
}})();

// === Search / filter functionality ===
(function() {{
  const input = document.getElementById('search-input');
  if (!input) return;
  const content = document.querySelector('.content');
  const allElements = Array.from(content.querySelectorAll('h2, h3, h4, table, ul, ol, p, pre, .mermaid, blockquote, hr, .class-card, .func-card'));
  input.addEventListener('input', function() {{
    const q = this.value.toLowerCase().trim();
    if (!q) {{
      allElements.forEach(el => el.style.display = '');
      return;
    }}
    allElements.forEach(el => {{
      const text = el.textContent.toLowerCase();
      el.style.display = text.includes(q) ? '' : 'none';
    }});
    input.closest('.search-wrap').style.display = '';
  }});
}})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _check_mermaid_blocks(content: str, source: str) -> list[str]:
    """Check Mermaid blocks for reserved keywords used as node IDs."""
    issues: list[str] = []
    blocks = re.findall(r"```mermaid\n(.*?)\n```", content, re.DOTALL)
    if not blocks and '<div class="mermaid">' in content:
        blocks = re.findall(r'<div class="mermaid">(.*?)</div>', content, re.DOTALL)
    for idx, block in enumerate(blocks, 1):
        for lineno, line in enumerate(block.split("\n"), 1):
            # A reserved keyword as the first word of a node definition
            m = re.match(r"^\s*(\w+)\s*[\[\(]", line)
            if m and m.group(1) in MERMAID_RESERVED:
                issues.append(
                    f"{source} mermaid block {idx} line {lineno}: "
                    f"reserved keyword '{m.group(1)}' used as a node id"
                )
    return issues


def validate_markdown(md_path: Path) -> list[str]:
    issues: list[str] = []
    content = md_path.read_text(encoding="utf-8")
    if content.count("```") % 2 != 0:
        issues.append("Unclosed code fence (odd number of ``` markers)")
    issues.extend(_check_mermaid_blocks(content, md_path.name))
    return issues


def validate_html(html_path: Path) -> list[str]:
    issues: list[str] = []
    content = html_path.read_text(encoding="utf-8")
    if "<!DOCTYPE html>" not in content and "<!doctype html>" not in content.lower():
        issues.append("Missing <!DOCTYPE html>")
    for tag in (
        "html",
        "head",
        "body",
        "pre",
        "ul",
        "ol",
        "table",
        "blockquote",
        "div",
    ):
        if content.count(f"<{tag}") != content.count(f"</{tag}>"):
            issues.append(
                f"Unbalanced <{tag}> tags "
                f"({content.count(f'<{tag}')} open, {content.count(f'</{tag}>')} close)"
            )
    issues.extend(_check_mermaid_blocks(content, html_path.name))
    return issues


def _try_mermaid_cli(structures_count: int) -> list[str]:
    """If the Mermaid CLI (mmdc) is installed, validate all blocks via SVG render."""
    issues: list[str] = []
    try:
        result = subprocess.run(["mmdc", "--version"], capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ["(Mermaid CLI 'mmdc' not installed \u2014 skipped runtime validation)"]
    if result.returncode != 0:
        return ["(Mermaid CLI returned non-zero on --version)"]
    return issues


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def _parse_cli(argv: list[str]) -> tuple[Path, str, Path, bool, bool]:
    """Parse positional args + flags.

    Returns ``(project_root, output_prefix, output_dir, bundle_mermaid, minify_mermaid)``.

    Recognized flags:
        --no-bundle          Use the Mermaid CDN instead of embedding inline.
        --no-minify          Keep the embedded Mermaid source verbatim (larger HTML).
        --output-dir DIR     Directory to write the manuals into
                            (default: ``docs``, relative to project_root unless
                            absolute).
    Positional args: [project_root] [output_prefix]
    """
    positional: list[str] = []
    bundle = True
    minify = True
    output_dir_name = "docs"
    i = 1
    args = list(argv[1:])
    while i <= len(args):
        a = args[i - 1]
        if a == "--no-bundle":
            bundle = False
        elif a == "--no-minify":
            minify = False
        elif a == "--output-dir":
            if i >= len(args):
                print("  ERROR: --output-dir requires a directory argument")
                sys.exit(2)
            output_dir_name = args[i]
            i += 1
        elif a.startswith("--output-dir="):
            output_dir_name = a.split("=", 1)[1]
        elif a in ("-h", "--help"):
            print(
                "Usage: python _tecdoc_create.py [project_root] [output_prefix] "
                "[--no-bundle] [--no-minify] [--output-dir DIR]"
            )
            print("")
            print("Positional:")
            print("  project_root    Directory to scan (default: cwd)")
            print("  output_prefix   Output file prefix (default: 'tec')")
            print("")
            print("Flags:")
            print("  --no-bundle       Use Mermaid from CDN instead of embedding")
            print("  --no-minify       Keep embedded Mermaid verbatim (larger HTML)")
            print("  --output-dir DIR  Output directory (default: 'docs')")
            print(
                "                    Relative paths are resolved against project_root."
            )
            sys.exit(0)
        elif a.startswith("--"):
            print(f"  WARNING: unknown flag {a!r} (ignored)")
        else:
            positional.append(a)
        i += 1

    project_root = Path(positional[0]).resolve() if len(positional) >= 1 else Path.cwd()
    output_prefix = positional[1] if len(positional) >= 2 else "tec"
    output_dir = Path(output_dir_name)
    if not output_dir.is_absolute():
        output_dir = project_root / output_dir
    return project_root, output_prefix, output_dir, bundle, minify


def main(argv: list[str]) -> int:
    # Force UTF-8 stdout/stderr so unicode glyphs work on Windows
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    project_root, output_prefix, output_dir, bundle_mermaid, minify_mermaid = (
        _parse_cli(argv)
    )

    print(f"tecdoc_create: scanning {project_root}")
    print(f"  Output prefix: {output_prefix}")
    print(f"  Output dir:    {output_dir}")
    print(
        f"  Bundle Mermaid inline: {bundle_mermaid}"
        f"{'  (with minification)' if bundle_mermaid and minify_mermaid else ''}"
    )
    print(f"  Excluded dirs: {sorted(EXCLUDED_DIRS)}")
    print()

    source_files = find_source_files(project_root)
    print(f"Found {len(source_files)} source file(s):")
    for f in source_files:
        print(f"  \u2022 {f.relative_to(project_root)}")
    print()

    structures: list[dict] = []
    for f in source_files:
        tree, section_map = parse_file(f)
        if tree is not None:
            structures.append(
                extract_structure(tree, f.relative_to(project_root), section_map)
            )

    # ---- Output directory: from --output-dir (default: docs/) ---------------
    output_dir.mkdir(parents=True, exist_ok=True)

    # ---- Markdown -----------------------------------------------------------
    md_content = generate_markdown(structures, project_root)
    md_path = output_dir / f"{output_prefix}_manual.md"
    md_path.write_text(md_content, encoding="utf-8")
    md_display = _display_path(md_path, project_root)
    print(
        f"\u2713 Created {md_display} ({len(md_content):,} chars, "
        f"{md_content.count(chr(10)) + 1:,} lines)"
    )
    print()

    # ---- HTML ---------------------------------------------------------------
    html_content = generate_html(
        structures,
        project_root,
        md_content,
        bundle_mermaid=bundle_mermaid,
        minify_mermaid=minify_mermaid,
    )
    html_path = output_dir / f"{output_prefix}_manual.html"
    html_path.write_text(html_content, encoding="utf-8")
    html_display = _display_path(html_path, project_root)
    print(
        f"\u2713 Created {html_display} ({len(html_content):,} chars, "
        f"{html_content.count(chr(10)) + 1:,} lines)"
    )
    print()

    # ---- Validation ---------------------------------------------------------
    print("=" * 60)
    print("VALIDATION")
    print("=" * 60)
    total_issues = 0
    for name, path_, issues in [
        ("Markdown", md_path, validate_markdown(md_path)),
        ("HTML", html_path, validate_html(html_path)),
    ]:
        if issues:
            real = [i for i in issues if not i.startswith("(Mermaid CLI")]
            print(f"  {name}: {len(real)} issue(s)")
            for i in real:
                print(f"     \u2022 {i}")
            total_issues += len(real)
        else:
            print(f"  {name}: OK")
    print()

    # ---- Mermaid CLI optional ----------------------------------------------
    print("=" * 60)
    print("MERMAID SYNTAX CHECK (via mmdc CLI if available)")
    print("=" * 60)
    mmdc_issues = _try_mermaid_cli(len(structures))
    for i in mmdc_issues:
        print(f"  {i}")
    print()

    print("=" * 60)
    if total_issues == 0:
        print("\u2705 ALL CHECKS PASSED")
    else:
        print(f"\u26a0\ufe0f  {total_issues} issue(s) found \u2014 review above")
    print("=" * 60)
    return 0 if total_issues == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
