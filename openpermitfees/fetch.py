"""Polite, stdlib-only retrieval of jurisdiction fee-schedule documents.

Design constraints that are not negotiable for a public collector:

* **Identify ourselves.** A named User-Agent with a contact URL is what keeps a
  city IT department from blocking the project outright.
* **Obey robots.txt, and fail CLOSED on ambiguity.** RFC 9309: a 4xx robots
  response means "no rules, crawl allowed"; a 5xx means "unavailable, treat as
  disallowed". An unreadable robots file must never quietly become permission.
* **Failure returns a reason, never an empty success.** ``FetchResult.ok`` is
  False with a populated ``reason``; callers turn that into a ``not_fetched`` row
  rather than a missing row, because a jurisdiction silently vanishing from the
  dataset looks exactly like a jurisdiction that charges nothing.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

__version__ = "0.1.0"

# The contact URL a permitting department will actually open when they see this
# in their logs. It must resolve to something that explains the crawler and
# takes an issue — the repository does both, today.
USER_AGENT = (
    f"openpermitfees/{__version__} (+https://github.com/USTechAutomations/openpermitfees; "
    "public fee-schedule collector)"
)

DEFAULT_TIMEOUT = 45
DEFAULT_RETRIES = 2
DEFAULT_DELAY_SECONDS = 1.0


@dataclass
class FetchResult:
    url: str
    ok: bool
    payload: Optional[bytes] = None
    media_type: str = ""
    http_status: Optional[int] = None
    retrieved_at: str = ""
    reason: Optional[str] = None
    final_url: Optional[str] = None

    @property
    def byte_length(self) -> int:
        return len(self.payload or b"")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class RobotsCache:
    """robots.txt decisions per origin, fail-closed on server error."""

    def __init__(self, user_agent: str = USER_AGENT, timeout: int = 15) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self._cache: dict[str, tuple[bool, Optional[urllib.robotparser.RobotFileParser]]] = {}

    def allows(self, url: str) -> tuple[bool, Optional[str]]:
        parts = urllib.parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._cache:
            self._cache[origin] = self._load(origin)
        allowed_by_default, parser = self._cache[origin]
        if parser is None:
            return (
                (True, None)
                if allowed_by_default
                else (False, "robots.txt unavailable (5xx) — treated as disallow")
            )
        if parser.can_fetch(self.user_agent, url):
            return True, None
        return False, "disallowed by robots.txt"

    def _load(
        self, origin: str
    ) -> tuple[bool, Optional[urllib.robotparser.RobotFileParser]]:
        request = urllib.request.Request(
            origin + "/robots.txt", headers={"User-Agent": self.user_agent}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            # 4xx: no rules published -> allowed. 5xx: unavailable -> disallowed.
            return (exc.code < 500, None)
        except Exception:
            return (False, None)
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(body.splitlines())
        return (True, parser)


def fetch(
    url: str,
    *,
    robots: Optional[RobotsCache] = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    user_agent: str = USER_AGENT,
    respect_robots: bool = True,
) -> FetchResult:
    """Retrieve one document. Never raises for network conditions."""
    if respect_robots:
        checker = robots or RobotsCache(user_agent=user_agent)
        allowed, why = checker.allows(url)
        if not allowed:
            return FetchResult(url=url, ok=False, reason=why, retrieved_at=_utc_now())

    last_reason: Optional[str] = None
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(delay_seconds * (2 ** (attempt - 1)))
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
                return FetchResult(
                    url=url,
                    ok=True,
                    payload=payload,
                    media_type=(response.headers.get("Content-Type") or "").split(";")[0].strip(),
                    http_status=response.status,
                    retrieved_at=_utc_now(),
                    final_url=response.url,
                )
        except urllib.error.HTTPError as exc:
            last_reason = f"HTTP {exc.code}"
            if exc.code < 500 and exc.code != 429:
                break  # 404/403 will not fix themselves on retry
        except urllib.error.URLError as exc:
            last_reason = f"network error: {exc.reason}"
        except Exception as exc:  # pragma: no cover - defensive
            last_reason = f"{type(exc).__name__}: {exc}"

    return FetchResult(url=url, ok=False, reason=last_reason or "unknown error", retrieved_at=_utc_now())


__all__ = ["DEFAULT_TIMEOUT", "FetchResult", "RobotsCache", "USER_AGENT", "fetch", "__version__"]
