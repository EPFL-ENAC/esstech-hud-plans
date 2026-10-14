from __future__ import annotations

from pathlib import Path

from api.config import config
from api.models.user import User

TERMS_LOCALES = ("en", "fr", "es")
TERMS_DIRECTORY = Path(__file__).resolve().parents[1] / "terms"


def _read_locale(version: str, locale: str) -> str:
    """Read the terms markdown for a locale, falling back to English."""

    path = TERMS_DIRECTORY / version / f"{locale}.md"
    if not path.is_file():
        path = TERMS_DIRECTORY / version / "en.md"
    return path.read_text(encoding="utf-8")


def terms_content() -> dict[str, str]:
    """Return the current terms markdown keyed by locale."""

    return {
        locale: _read_locale(config.TERMS_VERSION, locale) for locale in TERMS_LOCALES
    }


def is_accepted(user: User) -> bool:
    """True when the user accepted the current terms version."""

    return user.terms_accepted_version == config.TERMS_VERSION
