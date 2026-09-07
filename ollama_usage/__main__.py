"""Allow ``python -m ollama_usage`` (used by ``--daemon`` when the CLI is run
from source instead of the compiled binary)."""

from ollama_usage.cli import main

if __name__ == "__main__":
    main()