"""Load API keys from .env (local) and st.secrets (Streamlit Community Cloud)."""
from __future__ import annotations

import os
from typing import Any, Iterator

# Keys the app knows how to consume.
KNOWN_KEYS = (
    "OPENAI_API_KEY",
    "AIMLAPI_KEY",
    "XAI_API_KEY",
    "BRIGHTDATA_BROWSER_AUTH",
    "NCBI_API_KEY",
    "USER_EMAIL",
    "OPENALEX_API_KEY",
)
PLACEHOLDER_TOKENS = (
    "...",
    "replace-with",
    "sk-replace-with",
    "brd-customer-xxxx",
    "you@example.com",
)


def _looks_configured(value: str) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return False
    return not any(token in normalized for token in PLACEHOLDER_TOKENS)


def _iter_secret_pairs(obj: Any, prefix: str = "") -> Iterator[tuple[str, str]]:
    """Flatten Streamlit secrets — supports both flat and [section] TOML layouts."""
    if obj is None:
        return

    # Streamlit AttrDict / mapping with nested sections
    if hasattr(obj, "keys") and not isinstance(obj, str):
        for key in obj:
            value = obj[key]
            if isinstance(value, str):
                yield key, value.strip()
            elif isinstance(value, (int, float)):
                yield key, str(value)
            elif hasattr(value, "keys"):
                yield from _iter_secret_pairs(value, prefix=f"{prefix}.{key}" if prefix else key)
        return

    if isinstance(obj, str) and prefix:
        yield prefix.split(".")[-1], obj.strip()


def load_secrets() -> None:
    from dotenv import load_dotenv

    load_dotenv()

    try:
        import streamlit as st

        secrets = getattr(st, "secrets", None)
        if not secrets:
            return

        for key, value in _iter_secret_pairs(secrets):
            if not key or key.startswith("_"):
                continue
            if value and not os.environ.get(key):
                os.environ[key] = value
    except Exception:
        # No secrets file yet, or Streamlit running outside app context.
        pass

    # Explicit fallback for known keys (handles nested [api] sections).
    try:
        import streamlit as st

        for key in KNOWN_KEYS:
            if os.environ.get(key):
                continue
            try:
                value = st.secrets[key]
            except Exception:
                continue
            if isinstance(value, str) and value.strip():
                os.environ[key] = value.strip()
    except Exception:
        pass


def api_key_status() -> dict[str, bool]:
    """Return which API keys are present (never exposes values)."""
    load_secrets()
    return {key: _looks_configured(os.getenv(key, "")) for key in KNOWN_KEYS}


def required_keys_ok() -> bool:
    status = api_key_status()
    return status["OPENAI_API_KEY"] and status["AIMLAPI_KEY"]
