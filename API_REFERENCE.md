# RapidAPI Endpoints Reference

## 1. SEMrush Keyword Magic Tool
Host: semrush-keyword-magic-tool.p.rapidapi.com
- GET /global-volume?keyword=<kw>&country=us  → volume, competition, CPC

## 2. SimilarWeb Insights
Host: similarweb-insights.p.rapidapi.com
- GET /seo?domain=<domain>             → SEO metrics (backlinks, organic keywords)
- GET /traffic?domain=<domain>         → Traffic overview (visits, bounce rate)
- GET /ai-traffic?domain=<domain>      → AI-referred traffic
- GET /rank?domain=<domain>            → Global/country rank
- GET /website-details?domain=<domain> → Full site details
- GET /similar-sites?domain=<domain>   → Competitor list
- GET /country-metadata?domain=<domain>→ Country breakdown

## 3. Domain Metrics Check
Host: domain-metrics-check.p.rapidapi.com
- GET /domain-metrics/<domain>/        → DA, PA, spam score, backlinks

## 4. Google Keyword Insight
Host: google-keyword-insight1.p.rapidapi.com
- GET /keyword-research?keyword=<kw>&lang=en&country=us
- GET /keyword-research-by-url?url=<url>
- GET /global-results?keyword=<kw>
- GET /global-results-by-url?url=<url>
- GET /top-keyword?domain=<domain>
- GET /questions?keyword=<kw>
- GET /locations/
- GET /languages/

## 5. PageSpeed Insights
Host: pagespeed-insights.p.rapidapi.com
- GET /run_pagespeed?url=<url>&category=PERFORMANCE&strategy=DESKTOP

## Auth (all endpoints)
x-rapidapi-key: 9f107deaabmsh2efbc3559ddca05p17f1abjsn271e6df32f7c
