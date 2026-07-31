"""Retrieval politeness and the fail-closed robots rule.

RFC 9309: a 4xx robots.txt means "no rules published, crawling allowed"; a 5xx
means "unavailable, treat as disallowed". Collapsing those two into "we could not
read it, so go ahead" is how a public collector gets itself blocked — and it is
the same confident-default shape as publishing an unsourced fee.

No test here touches the network.
"""

from __future__ import annotations

import urllib.error

import pytest

from openpermitfees import fetch as fetch_module
from openpermitfees.fetch import RobotsCache, USER_AGENT, fetch


class _Response:
    def __init__(self, body: bytes, status: int = 200, content_type: str = "text/plain"):
        self._body = body
        self.status = status
        self.headers = {"Content-Type": content_type}
        self.url = "https://example.gov/fees.pdf"

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _raise(exc):
    def opener(request, timeout=None):
        raise exc

    return opener


def test_user_agent_names_the_project_and_a_contact_url():
    assert "openpermitfees/" in USER_AGENT
    assert "https://" in USER_AGENT


def test_robots_404_means_no_rules_and_crawling_is_allowed(monkeypatch):
    error = urllib.error.HTTPError("https://example.gov/robots.txt", 404, "Not Found", {}, None)
    monkeypatch.setattr(fetch_module.urllib.request, "urlopen", _raise(error))
    allowed, why = RobotsCache().allows("https://example.gov/fees.pdf")
    assert allowed is True and why is None


def test_robots_503_is_treated_as_disallow(monkeypatch):
    error = urllib.error.HTTPError("https://example.gov/robots.txt", 503, "Down", {}, None)
    monkeypatch.setattr(fetch_module.urllib.request, "urlopen", _raise(error))
    allowed, why = RobotsCache().allows("https://example.gov/fees.pdf")
    assert allowed is False
    assert "5xx" in why


def test_an_unreachable_robots_file_is_also_a_disallow(monkeypatch):
    monkeypatch.setattr(
        fetch_module.urllib.request, "urlopen", _raise(urllib.error.URLError("timed out"))
    )
    allowed, _ = RobotsCache().allows("https://example.gov/fees.pdf")
    assert allowed is False


def test_an_explicit_disallow_is_obeyed(monkeypatch):
    body = b"User-agent: *\nDisallow: /documents/\n"
    monkeypatch.setattr(
        fetch_module.urllib.request, "urlopen", lambda request, timeout=None: _Response(body)
    )
    robots = RobotsCache()
    assert robots.allows("https://example.gov/documents/fees.pdf")[0] is False
    assert robots.allows("https://example.gov/public/fees.pdf")[0] is True


def test_robots_is_fetched_once_per_origin(monkeypatch):
    calls = []

    def opener(request, timeout=None):
        calls.append(request.full_url)
        return _Response(b"User-agent: *\nAllow: /\n")

    monkeypatch.setattr(fetch_module.urllib.request, "urlopen", opener)
    robots = RobotsCache()
    robots.allows("https://example.gov/a.pdf")
    robots.allows("https://example.gov/b.pdf")
    assert calls == ["https://example.gov/robots.txt"]


def test_a_blocked_url_returns_a_reason_not_an_exception(monkeypatch):
    error = urllib.error.HTTPError("https://example.gov/robots.txt", 500, "Boom", {}, None)
    monkeypatch.setattr(fetch_module.urllib.request, "urlopen", _raise(error))
    result = fetch("https://example.gov/fees.pdf")
    assert result.ok is False
    assert result.payload is None
    assert "robots" in result.reason


def test_a_404_is_not_retried(monkeypatch):
    attempts = []

    def opener(request, timeout=None):
        attempts.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(fetch_module.urllib.request, "urlopen", opener)
    result = fetch("https://example.gov/fees.pdf", respect_robots=False, retries=3)
    assert result.ok is False
    assert result.reason == "HTTP 404"
    assert len(attempts) == 1, "a moved document will not un-move itself on retry"


def test_a_server_error_is_retried_then_reported(monkeypatch):
    attempts = []

    def opener(request, timeout=None):
        attempts.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 502, "Bad Gateway", {}, None)

    monkeypatch.setattr(fetch_module.urllib.request, "urlopen", opener)
    monkeypatch.setattr(fetch_module.time, "sleep", lambda seconds: None)
    result = fetch("https://example.gov/fees.pdf", respect_robots=False, retries=2)
    assert len(attempts) == 3
    assert result.ok is False and result.reason == "HTTP 502"


def test_a_successful_fetch_reports_bytes_media_type_and_time(monkeypatch):
    monkeypatch.setattr(
        fetch_module.urllib.request,
        "urlopen",
        lambda request, timeout=None: _Response(b"%PDF-1.7", content_type="application/pdf; q=1"),
    )
    result = fetch("https://example.gov/fees.pdf", respect_robots=False)
    assert result.ok and result.payload == b"%PDF-1.7"
    assert result.media_type == "application/pdf"
    assert result.http_status == 200
    assert result.retrieved_at.endswith("+00:00")
    assert result.byte_length == 8


@pytest.mark.parametrize("ok", [True, False])
def test_fetch_never_raises(monkeypatch, ok):
    if ok:
        monkeypatch.setattr(
            fetch_module.urllib.request, "urlopen", lambda request, timeout=None: _Response(b"x")
        )
    else:
        monkeypatch.setattr(
            fetch_module.urllib.request, "urlopen", _raise(RuntimeError("something exotic"))
        )
        monkeypatch.setattr(fetch_module.time, "sleep", lambda seconds: None)
    result = fetch("https://example.gov/fees.pdf", respect_robots=False, retries=0)
    assert result.ok is ok
