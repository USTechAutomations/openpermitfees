"""Per-jurisdiction extractors. Importing this package registers the built-ins."""

from . import phoenix  # noqa: F401  (registration side effect)
from .base import DocumentContext, Extractor, get, register, registered

__all__ = ["DocumentContext", "Extractor", "get", "register", "registered", "phoenix"]
