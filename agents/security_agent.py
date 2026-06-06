"""
Security Headers Agent
Checks HTTP security headers for a domain.
Inspired by StanGirard/seo-audits-toolkit (Mozilla Observatory pattern).
Pure Python — no external CLI required.
"""
import asyncio
import time
from typing import Any

import aiohttp


# Security headers to check, with severity and description
SECURITY_HEADERS = {
    "strict-transport-security": {
        "severity": "critical",
        "description": "HTTP Strict Transport Security (HSTS)",
        "recommendation": "Add: Strict-Transport-Security: max-age=31536000; includeSubDomains",
        "good_pattern": None,  # just presence is enough
    },
    "content-security-policy": {
        "severity": "high",
        "description": "Content Security Policy (CSP)",
        "recommendation": "Add a Content-Security-Policy header to prevent XSS attacks",
        "good_pattern": None,
    },
    "x-frame-options": {
        "severity": "medium",
        "description": "X-Frame-Options (clickjacking protection)",
        "recommendation": "Add: X-Frame-Options: DENY or SAMEORIGIN",
        "good_pattern": None,
    },
    "x-content-type-options": {
        "severity": "medium",
        "description": "X-Content-Type-Options (MIME sniffing protection)",
        "recommendation": "Add: X-Content-Type-Options: nosniff",
        "good_pattern": "nosniff",
    },
    "referrer-policy": {
        "severity": "low",
        "description": "Referrer-Policy",
        "recommendation": "Add: Referrer-Policy: strict-origin-when-cross-origin",
        "good_pattern": None,
    },
    "permissions-policy": {
        "severity": "low",
        "description": "Permissions-Policy (formerly Feature-Policy)",
        "recommendation": "Add a Permissions-Policy header to restrict browser features",
        "good_pattern": None,
    },
    "x-xss-protection": {
        "severity": "low",
        "description": "X-XSS-Protection (legacy, but still checked)",
        "recommendation": "Add: X-XSS-Protection: 1; mode=block (or rely on CSP instead)",
        "good_pattern": None,
    },
}

# Informational headers (not security issues, but useful to surface)
INFO_HEADERS = [
    "server",
    "x-powered-by",
    "via",
    "x-generator",
]

SEVERITY_SCORE = {"critical": 30, "high": 20, "medium": 10, "low": 5}


def _score_grade(score: int) -> str:
    if score >= 90: return "A+"
    if score >= 80: return "A"
    if score >= 70: return "B"
    if score >= 60: return "C"
    if score >= 50: return "D"
    return "F"


async def run_security_audit(domain: str) -> dict[str, Any]:
    """
    Fetch HTTP headers for `domain` and evaluate security posture.

    Returns:
      - headers_present: dict of security headers found
      - headers_missing: list of missing headers with severity + recommendation
      - info_headers: informational headers (server, x-powered-by, etc.)
      - https: bool — whether HTTPS is used
      - redirects_to_https: bool — whether HTTP redirects to HTTPS
      - score: 0-100
      - grade: A+/A/B/C/D/F
      - issues: list of {severity, header, description, recommendation}
    """
    url = f"https://{domain}" if not domain.startswith("http") else domain
    http_url = url.replace("https://", "http://")

    connector = aiohttp.TCPConnector(ssl=False)
    timeout = aiohttp.ClientTimeout(total=20, connect=10)
    headers_ua = {"User-Agent": "Mozilla/5.0 (compatible; SEOBot/1.0)"}

    result = {
        "domain": domain,
        "url": url,
        "https": False,
        "redirects_to_https": False,
        "status_code": 0,
        "response_time_ms": 0,
        "headers_present": {},
        "headers_missing": [],
        "info_headers": {},
        "issues": [],
        "score": 0,
        "grade": "F",
        "error": None,
    }

    try:
        t0 = time.monotonic()
        async with aiohttp.ClientSession(connector=connector, timeout=timeout, headers=headers_ua) as session:
            # Check HTTPS
            try:
                async with session.get(url, allow_redirects=True) as resp:
                    result["response_time_ms"] = int((time.monotonic() - t0) * 1000)
                    result["status_code"] = resp.status
                    result["https"] = str(resp.url).startswith("https://")
                    raw_headers = dict(resp.headers)
            except Exception as e:
                result["error"] = f"HTTPS fetch failed: {e}"
                return result

            # Check HTTP → HTTPS redirect
            try:
                async with session.get(http_url, allow_redirects=False) as http_resp:
                    location = http_resp.headers.get("location", "")
                    result["redirects_to_https"] = (
                        http_resp.status in (301, 302, 307, 308)
                        and location.startswith("https://")
                    )
            except Exception:
                pass  # HTTP may be blocked; not a hard failure

    except Exception as e:
        result["error"] = str(e)
        return result

    # Normalize header names to lowercase
    lower_headers = {k.lower(): v for k, v in raw_headers.items()}

    # Evaluate security headers
    max_possible = sum(SEVERITY_SCORE[v["severity"]] for v in SECURITY_HEADERS.values())
    # HTTPS bonus
    https_bonus = 20
    max_possible += https_bonus
    earned = https_bonus if result["https"] else 0

    for header_name, meta in SECURITY_HEADERS.items():
        if header_name in lower_headers:
            result["headers_present"][header_name] = lower_headers[header_name]
            earned += SEVERITY_SCORE[meta["severity"]]
        else:
            result["headers_missing"].append({
                "header": header_name,
                "severity": meta["severity"],
                "description": meta["description"],
                "recommendation": meta["recommendation"],
            })
            result["issues"].append({
                "severity": meta["severity"],
                "header": header_name,
                "description": meta["description"],
                "recommendation": meta["recommendation"],
            })

    # HTTPS redirect issue
    if not result["redirects_to_https"]:
        result["issues"].append({
            "severity": "critical",
            "header": "http-to-https-redirect",
            "description": "HTTP does not redirect to HTTPS",
            "recommendation": "Configure a 301 redirect from http:// to https://",
        })

    # Info headers (server fingerprinting)
    for h in INFO_HEADERS:
        if h in lower_headers:
            result["info_headers"][h] = lower_headers[h]

    # Score
    score = int((earned / max_possible) * 100) if max_possible > 0 else 0
    result["score"] = min(score, 100)
    result["grade"] = _score_grade(result["score"])

    # Sort issues by severity
    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    result["issues"].sort(key=lambda x: sev_order.get(x["severity"], 99))

    return result
