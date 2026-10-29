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
    groq_model: str = "qwen/qwen3.8-27b"
    groq_api_key: str | None = None

    agent_max_steps: int = 10
    agent_preflight: bool = True
    database_url: str = f"sqlite:///{(ROOT / 'data' / 'safeops.db').as_posix()}"
    audit_log_path: Path = ROOT / "data" / "audit.jsonl"

    auth_jwt_secret: str | None = None
    auth_token_minutes: int = 30
    auth_demo_users: bool = True
    auth_demo_password: str = "safeops-demo"
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_roles_claim: str = "roles"


settings = Settings()
