"""
OnPage SEO Agent
Fetches a URL, extracts full on-page SEO data, and runs issue detection.
Adapted from LibreCrawl (PhialsBasement/LibreCrawl) SEOExtractor + IssueDetector.
"""
import asyncio
import re
import json
import time
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup


class _SEOExtractor:
    @staticmethod
    def extract(html: str, url: str, response_time_ms: int, status_code: int, size: int) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        parsed = urlparse(url)
        base_domain = parsed.netloc
        result = _SEOExtractor._empty(url, status_code, size, response_time_ms)
        _SEOExtractor._basic(soup, result)
        _SEOExtractor._meta_tags(soup, result)
        _SEOExtractor._og_tags(soup, result)
        _SEOExtractor._twitter_tags(soup, result)
        _SEOExtractor._json_ld(soup, result)
        _SEOExtractor._analytics(soup, html, result)
        _SEOExtractor._images(soup, url, result)
        _SEOExtractor._links(soup, result, base_domain)
        _SEOExtractor._hreflang(soup, result)
        _SEOExtractor._schema_org(soup, result)
        return result

    @staticmethod
    def _empty(url, status_code, size, response_time):
        return {
            "url": url, "status_code": status_code, "size": size,
            "response_time": response_time, "title": "", "meta_description": "",
            "h1": "", "h2": [], "h3": [], "word_count": 0, "lang": "",
            "charset": "", "viewport": "", "robots": "", "author": "",
            "keywords": "", "canonical_url": "", "meta_tags": {}, "og_tags": {},
            "twitter_tags": {}, "json_ld": [], "schema_org": [], "hreflang": [],
            "analytics": {"google_analytics": False, "gtag": False, "ga4_id": "",
                          "gtm_id": "", "facebook_pixel": False, "hotjar": False, "mixpanel": False},
            "images": [], "internal_links": 0, "external_links": 0,
        }

    @staticmethod
    def _basic(soup, result):
        t = soup.find("title")
        result["title"] = t.get_text().strip() if t else ""
        md = soup.find("meta", attrs={"name": "description"})
        result["meta_description"] = md.get("content", "").strip() if md else ""
        h1 = soup.find("h1")
        result["h1"] = h1.get_text().strip() if h1 else ""
        result["h2"] = [h.get_text().strip() for h in soup.find_all("h2")[:10]]
        result["h3"] = [h.get_text().strip() for h in soup.find_all("h3")[:10]]
        result["word_count"] = len(re.findall(r"\b\w+\b", soup.get_text()))
        html_tag = soup.find("html")
        result["lang"] = html_tag.get("lang", "") if html_tag else ""
        cm = soup.find("meta", attrs={"charset": True})
        if cm:
            result["charset"] = cm.get("charset", "")

    @staticmethod
    def _meta_tags(soup, result):
        for meta in soup.find_all("meta"):
            name = meta.get("name", "").lower()
            content = meta.get("content", "")
            if name:
                result["meta_tags"][name] = content
                if name == "viewport": result["viewport"] = content
                elif name == "robots": result["robots"] = content
                elif name == "author": result["author"] = content
                elif name == "keywords": result["keywords"] = content
        canonical = soup.find("link", attrs={"rel": "canonical"})
        result["canonical_url"] = canonical.get("href", "") if canonical else ""

    @staticmethod
    def _og_tags(soup, result):
        for meta in soup.find_all("meta", attrs={"property": re.compile(r"^og:")}):
            result["og_tags"][meta.get("property", "").replace("og:", "")] = meta.get("content", "")

    @staticmethod
    def _twitter_tags(soup, result):
        for meta in soup.find_all("meta", attrs={"name": re.compile(r"^twitter:")}):
            result["twitter_tags"][meta.get("name", "").replace("twitter:", "")] = meta.get("content", "")

    @staticmethod
    def _json_ld(soup, result):
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                result["json_ld"].append(json.loads(script.string))
            except Exception:
                pass

    @staticmethod
    def _analytics(soup, html, result):
        ga4 = re.search(r"G-[A-Z0-9]{10}", html)
        if ga4:
            result["analytics"]["ga4_id"] = ga4.group()
            result["analytics"]["gtag"] = True
        gtm = re.search(r"GTM-[A-Z0-9]+", html)
        if gtm:
            result["analytics"]["gtm_id"] = gtm.group()
        for pat in [r"gtag\(", r"ga\(", r"GoogleAnalyticsObject", r"google-analytics\.com", r"googletagmanager\.com"]:
            if re.search(pat, html, re.IGNORECASE):
                result["analytics"]["google_analytics"] = True
                break
        if re.search(r"fbq\(|facebook\.com/tr", html, re.IGNORECASE):
            result["analytics"]["facebook_pixel"] = True
        if re.search(r"hotjar\.com|hj\(", html, re.IGNORECASE):
            result["analytics"]["hotjar"] = True
        if re.search(r"mixpanel\.com|mixpanel\.track", html, re.IGNORECASE):
            result["analytics"]["mixpanel"] = True

    @staticmethod
    def _images(soup, base_url, result):
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if src:
                if src.startswith("//"): src = "https:" + src
                elif src.startswith("/"):
                    p = urlparse(base_url)
                    src = f"{p.scheme}://{p.netloc}{src}"
                elif not src.startswith(("http://", "https://")):
                    src = urljoin(base_url, src)
                result["images"].append({"src": src, "alt": img.get("alt", "")})

    @staticmethod
    def _links(soup, result, base_domain):
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if href and not href.startswith(("#", "mailto:", "tel:", "javascript:")):
                abs_url = urljoin(result["url"], href)
                parsed = urlparse(abs_url)
                if parsed.netloc.replace("www.", "") == base_domain.replace("www.", ""):
                    result["internal_links"] += 1
                else:
                    result["external_links"] += 1

    @staticmethod
    def _hreflang(soup, result):
        for link in soup.find_all("link", attrs={"rel": "alternate", "hreflang": True}):
            result["hreflang"].append({"lang": link.get("hreflang", ""), "url": link.get("href", "")})

    @staticmethod
    def _schema_org(soup, result):
        for item in soup.find_all(attrs={"itemtype": True}):
            result["schema_org"].append({"type": item.get("itemtype", "")})


class _IssueDetector:
    @staticmethod
    def detect(result: dict) -> list:
        issues = []
        title = result.get("title", "")
        if not title:
            issues.append({"type": "error", "category": "SEO", "issue": "Missing Title Tag", "details": "Page has no title tag"})
        elif len(title) > 60:
            issues.append({"type": "warning", "category": "SEO", "issue": "Title Too Long", "details": f"Title is {len(title)} chars (recommended <=60)"})
        elif len(title) < 30:
            issues.append({"type": "warning", "category": "SEO", "issue": "Title Too Short", "details": f"Title is {len(title)} chars (recommended 30-60)"})

        meta = result.get("meta_description", "")
        if not meta:
            issues.append({"type": "error", "category": "SEO", "issue": "Missing Meta Description", "details": "Page has no meta description"})
        elif len(meta) > 160:
            issues.append({"type": "warning", "category": "SEO", "issue": "Meta Description Too Long", "details": f"Description is {len(meta)} chars (recommended <=160)"})
        elif len(meta) < 120:
            issues.append({"type": "warning", "category": "SEO", "issue": "Meta Description Too Short", "details": f"Description is {len(meta)} chars (recommended 120-160)"})

        if not result.get("h1"):
            issues.append({"type": "error", "category": "SEO", "issue": "Missing H1 Tag", "details": "Page has no H1 heading"})

        wc = result.get("word_count", 0)
        if wc < 300:
            issues.append({"type": "warning", "category": "Content", "issue": "Thin Content", "details": f"Page has only {wc} words (recommended >=300)"})

        if not result.get("canonical_url"):
            issues.append({"type": "warning", "category": "Technical", "issue": "Missing Canonical URL", "details": "Page has no canonical URL"})

        if not result.get("viewport"):
            issues.append({"type": "error", "category": "Mobile", "issue": "Missing Viewport Meta Tag", "details": "Page is not mobile-optimized"})

        if not result.get("lang"):
            issues.append({"type": "warning", "category": "Accessibility", "issue": "Missing Language Attribute", "details": "HTML tag has no lang attribute"})

        images = result.get("images", [])
        no_alt = [i for i in images if not i.get("alt")]
        if no_alt:
            issues.append({"type": "warning", "category": "Accessibility", "issue": "Images Without Alt Text", "details": f"{len(no_alt)} of {len(images)} images lack alt text"})

        if not result.get("og_tags"):
            issues.append({"type": "warning", "category": "Social", "issue": "Missing OpenGraph Tags", "details": "Page has no OpenGraph tags for social sharing"})

        if not result.get("twitter_tags"):
            issues.append({"type": "warning", "category": "Social", "issue": "Missing Twitter Card Tags", "details": "Page has no Twitter Card tags"})

        if not result.get("json_ld") and not result.get("schema_org"):
            issues.append({"type": "error", "category": "Structured Data", "issue": "No Structured Data", "details": "Page has no JSON-LD or Schema.org markup"})

        rt = result.get("response_time", 0)
        if rt > 3000:
            issues.append({"type": "error", "category": "Performance", "issue": "Slow Response Time", "details": f"Page took {rt}ms (recommended <3000ms)"})
        elif rt > 1000:
            issues.append({"type": "warning", "category": "Performance", "issue": "Moderate Response Time", "details": f"Page took {rt}ms (recommended <1000ms)"})

        robots = result.get("robots", "").lower()
        if "noindex" in robots:
            issues.append({"type": "error", "category": "Indexability", "issue": "Noindex Tag Present", "details": "Page is blocked from search engines"})
        if "nofollow" in robots:
            issues.append({"type": "error", "category": "Indexability", "issue": "Nofollow Tag Present", "details": "Links on this page are not followed by search engines"})

        return issues


async def run_onpage_audit(domain: str) -> dict:
    url = f"https://{domain}" if not domain.startswith("http") else domain
    connector = aiohttp.TCPConnector(ssl=False)
    timeout = aiohttp.ClientTimeout(total=30, connect=10)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; SEOBot/1.0)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    try:
        t0 = time.monotonic()
        async with aiohttp.ClientSession(connector=connector, timeout=timeout, headers=headers) as session:
            async with session.get(url, allow_redirects=True) as resp:
                response_time_ms = int((time.monotonic() - t0) * 1000)
                html = await resp.text(errors="replace")
                status_code = resp.status
                size = len(html.encode("utf-8"))
                final_url = str(resp.url)
        page_data = _SEOExtractor.extract(html, final_url, response_time_ms, status_code, size)
        issues = _IssueDetector.detect(page_data)
        errors = [i for i in issues if i["type"] == "error"]
        warnings = [i for i in issues if i["type"] == "warning"]
        return {
            "page_data": page_data,
            "issues": issues,
            "summary": {
                "total": len(issues),
                "errors": len(errors),
                "warnings": len(warnings),
                "infos": len(issues) - len(errors) - len(warnings),
                "is_spa": page_data["word_count"] < 50,
            },
        }
    except asyncio.TimeoutError:
        return {"error": "timeout", "page_data": {}, "issues": [], "summary": {"total": 0, "errors": 0, "warnings": 0, "infos": 0, "is_spa": False}}
    except Exception as e:
        return {"error": str(e), "page_data": {}, "issues": [], "summary": {"total": 0, "errors": 0, "warnings": 0, "infos": 0, "is_spa": False}}
