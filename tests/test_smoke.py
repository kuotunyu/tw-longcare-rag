"""Phase 0 骨架煙霧測試。"""

from twlongcare import __version__
from twlongcare.config import REPO_ROOT, get_settings


def test_version() -> None:
    assert __version__


def test_settings_have_model_strings() -> None:
    s = get_settings()
    assert s.gemini_model
    assert s.gemini_lite_model
    assert s.openai_model
    assert s.ollama_model


def test_trace_redaction_is_privacy_safe_by_default(monkeypatch) -> None:
    """未明確設定時，公開或本機 trace 都不應保留常見個資原文。"""
    monkeypatch.delenv("RAG_TRACE_REDACT_PII", raising=False)
    get_settings.cache_clear()
    try:
        redact_pii = get_settings().trace_redact_pii
        assert redact_pii is True
    finally:
        get_settings.cache_clear()


def test_repo_layout() -> None:
    assert (REPO_ROOT / "pyproject.toml").exists()
    assert (REPO_ROOT / ".env.example").exists()
