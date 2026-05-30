"""Load API keys from .env (local) and st.secrets (Streamlit Community Cloud)."""
from __future__ import annotations

import os


def load_secrets() -> None:
    from dotenv import load_dotenv

    load_dotenv()

    try:
        import streamlit as st

        secrets = getattr(st, "secrets", None)
        if not secrets:
            return
        for key in secrets:
            if key.startswith("_"):
                continue
            value = secrets[key]
            if isinstance(value, str) and value and not os.environ.get(key):
                os.environ[key] = value
    except Exception:
        pass
