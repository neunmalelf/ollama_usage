"""ollama_usage - CLI and library to check your Ollama Cloud quota usage.

The package version is ``MAJOR.MINOR.YYYYMMDDhhmmss``: the micro segment is a
14-digit UTC timestamp (no trailing ``Z``), as printed by ``~/sbin/timestamp``
and required for a PEP 440-valid version.
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

__version__ = "3.0.20261111132215"

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
