"""Custom exceptions for ollama_usage."""


class OllamaUsageError(Exception):
    """Base exception for ollama_usage."""


class AuthError(OllamaUsageError):
    """Raised when the session cookie is invalid or expired."""


class ParseError(OllamaUsageError):
    """Raised when the HTML structure is unexpected or incomplete."""


class LayoutChangedError(ParseError):
    """Raised when ollama.com/settings is missing an element the parser needs.

    The message is one sentence naming what was expected, so the CLI, the
    widget and the GUI can show it as-is. ``detail`` additionally carries the
    anchor inventory of the fetched page ("found: ...; missing: ..."), which
    the CLI prints underneath the message.
    """

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


class NetworkError(OllamaUsageError):
    """Raised when a network request fails."""


class BrowserNotFoundError(OllamaUsageError):
    """Raised when a browser profile or cookie store cannot be located."""


class UnsupportedOSError(OllamaUsageError):
    """Raised when the current OS is not supported for a given browser."""