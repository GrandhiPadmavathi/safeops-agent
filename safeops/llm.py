from __future__ import annotations

import os
from typing import Any

from safeops.config import Settings, settings


def describe_model(cfg: Settings = settings) -> str:
    if cfg.llm_provider == "groq":
        return f"groq:{cfg.groq_model}"
    return f"ollama:{cfg.ollama_model}"


def make_llm(cfg: Settings = settings) -> Any:
    """Return a LangChain chat model for the configured provider (temperature 0)."""
    if cfg.llm_provider == "groq":
        api_key = cfg.groq_api_key or os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError(
                "SAFEOPS_LLM_PROVIDER=groq needs SAFEOPS_GROQ_API_KEY (or GROQ_API_KEY)."
            )
        from langchain_groq import ChatGroq

        return ChatGroq(model=cfg.groq_model, api_key=api_key, temperature=0)

    from langchain_ollama import ChatOllama

    return ChatOllama(model=cfg.ollama_model, base_url=cfg.ollama_base_url, temperature=0)
