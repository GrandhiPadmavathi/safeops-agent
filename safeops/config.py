from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_prefix="SAFEOPS_", extra="ignore"
    )

    llm_provider: Literal["ollama", "groq"] = "ollama"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b"
    groq_model: str = "llama-3.1-8b-instant"
    groq_api_key: str | None = None

    agent_max_steps: int = 10
    agent_preflight: bool = True
    database_url: str = f"sqlite:///{(ROOT / 'data' / 'safeops.db').as_posix()}"
    audit_log_path: Path = ROOT / "data" / "audit.jsonl"


settings = Settings()
