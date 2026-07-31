"""Extractor contract and registry.

An extractor is written per jurisdiction, on purpose. Generic "find the dollar
signs" parsing is how a residential mechanical permit ends up priced at a sign
inspection fee: the documents share no layout, no vocabulary, and no notion of
what a "residential permit" is. Ten jurisdictions parsed impeccably beat a
hundred parsed statistically, because one wrong published number costs more
credibility than ninety missing ones.

An extractor MUST:

* return ``FeeItem``s whose provenance quotes the line it read (the models layer
  enforces that the amount actually appears in the quote);
* return a ``not_found_in_document`` row rather than nothing when an expected fee
  is absent, so the dataset can distinguish "we looked and it is not there" from
  "nobody has looked";
* never infer, average, or regionally estimate a number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from ..models import FeeDocument, FeeItem
from .pdftext import TextLine


@dataclass(frozen=True)
class DocumentContext:
    """Everything an extractor is allowed to see."""

    document: FeeDocument
    lines: list[TextLine]

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


class Extractor(Protocol):
    jurisdiction_id: str

    def document_facts(self, context: DocumentContext) -> dict:
        """Self-described document metadata (ordinance, effective date, title)."""

    def extract(self, context: DocumentContext) -> list[FeeItem]:
        """Fee rows for this document."""


_REGISTRY: dict[str, Extractor] = {}


def register(extractor: Extractor) -> Extractor:
    _REGISTRY[extractor.jurisdiction_id] = extractor
    return extractor


def get(jurisdiction_id: str) -> Optional[Extractor]:
    return _REGISTRY.get(jurisdiction_id)


def registered() -> dict[str, Extractor]:
    return dict(_REGISTRY)


def clear() -> None:
    """Test-only: drop registered extractors."""
    _REGISTRY.clear()


ExtractorFactory = Callable[[], Extractor]

__all__ = [
    "DocumentContext",
    "Extractor",
    "clear",
    "get",
    "register",
    "registered",
]
