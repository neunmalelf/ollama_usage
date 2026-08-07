# Contributing to ollama_usage

Thanks for your interest in contributing! This project is open source under the MIT license.

## Getting started

1. Fork the repository and clone your fork.
2. Create a virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate      # Windows
   source .venv/bin/activate   # Linux / macOS
   ```
3. Install in editable mode with dev dependencies:
   ```bash
   pip install -e ".[dev]"
   ```
4. Run the test suite:
   ```bash
   pytest
   ```

## Code style

- Target Python 3.9+.
- Keep the public API (`ollama_usage/__init__.py`) stable.
- Do not add external runtime dependencies unless necessary.

## Testing

- Add or update tests under `tests/` for any new behaviour.
- The CLI depends on reading a browser cookie; unit tests must not require a
  live browser or network access.

## Commits

- Write clear, concise commit messages.
- Reference the related issue or PR where applicable.

## Submitting changes

1. Create a branch for your change.
2. Commit your work with a descriptive message.
3. Push the branch and open a pull request against `main`.
4. In the PR description, explain what you changed and why, and note any
   behaviour or CLI flag changes.

## Reporting issues

If you find a bug, please open an issue. Include:

- Your OS and browser
- The exact command you ran
- Whether it works with `--debug` and what it prints
- (If relevant) the expected vs. actual output

## License

By contributing you agree that your contributions are licensed under the
[MIT license](LICENSE).
