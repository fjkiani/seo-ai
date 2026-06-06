"""
core/config.py — Centralised settings loaded from environment variables.
All API keys and hosts live here. Never hardcode credentials.
"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    rapidapi_key: str
    openrouter_key: str

    # RapidAPI hosts (verified live 2026-06-04)
    semrush_host: str = "semrush-keyword-magic-tool.p.rapidapi.com"
    similarweb_host: str = "similarweb-insights.p.rapidapi.com"
    domain_metrics_host: str = "domain-metrics-check.p.rapidapi.com"
    google_kw_host: str = "google-keyword-insight1.p.rapidapi.com"
    pagespeed_host: str = "pagespeed-insights.p.rapidapi.com"

    # OpenRouter
    openrouter_base: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct"

    # SCI formula weights
    sci_relevance_default: float = 0.8
    sci_competitor_default: float = 1.0


def get_settings() -> Settings:
    """
    Load settings from environment. RAPIDAPI_KEY is optional at startup —
    endpoints that require it will return 503 if it's missing.
    This allows the /health endpoint to return 200 even without RAPIDAPI_KEY,
    so Render health checks pass during initial deployment.
    """
    rapidapi_key = os.getenv("RAPIDAPI_KEY", "")
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    return Settings(rapidapi_key=rapidapi_key, openrouter_key=openrouter_key)


def require_rapidapi_key() -> str:
    """Call this inside endpoints that need RAPIDAPI_KEY. Raises 503 if missing."""
    key = os.getenv("RAPIDAPI_KEY", "")
    if not key:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=503,
            detail="RAPIDAPI_KEY not configured. Set it in the Render dashboard.",
        )
    return key
