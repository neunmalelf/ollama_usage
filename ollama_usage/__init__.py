"""ollama_usage - CLI and library to check your Ollama Cloud quota usage.

The package version is ``MAJOR.MINOR.YYYYMMDDhhmmssZ``: the micro segment is a
UTC timestamp (the trailing ``Z`` marks UTC).
"""

from ollama_usage.scraper import get_usage
from ollama_usage.exceptions import (
    OllamaUsageError,
    AuthError,
    ParseError,
    NetworkError,
    BrowserNotFoundError,
    UnsupportedOSError,
)

__version__ = "2.0.20260911213613Z"

__all__ = [
    "__version__",
    "get_usage",
    "OllamaUsageError",
    "AuthError",
    "ParseError",
    "NetworkError",
    "BrowserNotFoundError",
    "UnsupportedOSError",
]
