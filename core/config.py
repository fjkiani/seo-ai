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
    openrouter_model: str = "anthropic/claude-3.5-haiku"

    # SCI formula weights
    sci_relevance_default: float = 0.8
    sci_competitor_default: float = 1.0


def get_settings() -> Settings:
    rapidapi_key = os.getenv("RAPIDAPI_KEY", "")
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if not rapidapi_key:
        raise EnvironmentError("RAPIDAPI_KEY environment variable is not set")
    return Settings(rapidapi_key=rapidapi_key, openrouter_key=openrouter_key)
