"""集中設定：金鑰與模型字串一律讀 .env，程式不寫死。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
LOGS_DIR = REPO_ROOT / "logs"


@dataclass(frozen=True)
class Settings:
    google_api_key: str
    openai_api_key: str
    hf_token: str
    discord_webhook_url: str
    gemini_model: str
    gemini_lite_model: str
    openai_model: str
    ollama_model: str
    embedding_model: str
    embedding_baseline_model: str
    reranker_model: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(REPO_ROOT / ".env")
    return Settings(
        google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        hf_token=os.getenv("HF_TOKEN", ""),
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
        gemini_lite_model=os.getenv("GEMINI_LITE_MODEL", "gemini-2.5-flash-lite"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        ollama_model=os.getenv("OLLAMA_MODEL", "taide-gemma3-12b"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "taide/embeddinggemma-GTAIDE-300m-2605"),
        embedding_baseline_model=os.getenv("EMBEDDING_BASELINE_MODEL", "BAAI/bge-m3"),
        reranker_model=os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
    )
