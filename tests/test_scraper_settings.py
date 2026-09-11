from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from src.core.services.scraper.scraper import build_cookie_jar
from src.settings.scraper_settings import ScraperCookieSettings


def test_cookie_jar_scopes_secrets_and_preserves_expiration() -> None:
    expires_at = datetime(2026, 11, 27, 12, 50, 2, tzinfo=UTC)
    configured = ScraperCookieSettings(
        name="cid",
        value=SecretStr("secret-value"),
        domain="www.coolstuffinc.com",
        path="/",
        expires_at=expires_at,
    )
    cookies = build_cookie_jar((configured,))

    assert cookies.get("cid", domain="www.coolstuffinc.com", path="/") == (
        "secret-value"
    )
    stored = next(iter(cookies.jar))
    assert stored.secure is True
    assert stored.expires == int(expires_at.timestamp())
    assert "secret-value" not in repr(configured)


def test_cookie_is_not_sent_to_another_domain() -> None:
    cookies = build_cookie_jar(
        (
            ScraperCookieSettings(
                name="grid",
                value=SecretStr("0"),
            ),
        )
    )
    same_domain = httpx.Request("GET", "https://www.coolstuffinc.com/path")
    other_domain = httpx.Request("GET", "https://example.com/path")
    cookies.set_cookie_header(same_domain)
    cookies.set_cookie_header(other_domain)

    assert same_domain.headers["Cookie"] == "grid=0"
    assert "Cookie" not in other_domain.headers


def test_cookie_rejects_an_unrelated_domain() -> None:
    with pytest.raises(ValidationError):
        ScraperCookieSettings(
            name="cid",
            value=SecretStr("secret"),
            domain="example.com",
        )
