# Powerling Pre-Audit System

## Goal

Automate the Powerling pre-audit report - a deliverable Powerling sends to prospective clients that analyzes their website across multiple digital pillars and benchmarks them against their competitors.

The manual workflow was:
1. Account manager gathers the client URL and competitor URLs
2. Uses SEMrush manually for SEO/health data
3. Feeds everything into a custom GPT via ChatGPT.com
4. Validates the output manually
5. Exports to PDF and delivers to the client

The goal is to fully automate this: submit a URL → get a structured, professional-quality report as output.

---

## Audit Structure (Pillars)

### Pillar 1: Globalization
- Language Coverage Rate (LCR) = (Available Languages / Required Languages) × 100
- LCR computed deterministically from Playwright-crawled data - not AI-guessed
- Hreflang tags, x-default, locale URLs, language selector type, mixed-language UX issues
- Geographic presence, required languages, traffic estimates (GPT research)

### Pillar 2: Website Health
- Google PageSpeed Insights: performance, SEO, accessibility scores, Core Web Vitals (LCP, CLS, INP)
- DataForSEO OnPage crawl: site health score, broken links, missing titles/meta/H1s, canonicals, thin content, crawl depth, orphan pages
- Homepage technical checks: robots.txt, sitemap.xml, llms.txt, HSTS, HTTPS redirect, schema markup, H1

### Pillar 3: Accessibility & Compliance
- WCAG issues, accessibility statement, cookie consent (CMP provider), privacy policy, ToS, sitemap
- GDPR/CNIL/RGAA/ADA compliance indicators
- Cookie banner detected via Playwright (authoritative) - not GPT-inferred
- Primary region + applicable regulations inferred from locale data

### Pillar 4: Online Reputation
- Social media: LinkedIn, X, Instagram, Facebook, YouTube (followers + last active)
- YouTube channel verified via YouTube Data API v3 before GPT research
- Review scores: Trustpilot, Google Reviews, Glassdoor (rating, CEO approval, % recommend), Indeed
- Credibility assets, trade fair presence, recent news, controversies, overall sentiment

### Competitive Landscape + Conclusion
- Stored in facts pack; generated via GPT-5 in `generate_ui_content()`
- Competitive landscape: cross-pillar comparison table (client vs. 3 competitors)
- Conclusion: positives, negatives, top 5 recommendations, combined ROI

---

## Tech Stack

### Backend
- **FastAPI** - REST API server
- **SQLite + SQLAlchemy** - Job persistence (status tracking, result storage)
- **OpenAI Python SDK** - All AI calls
  - `gpt-4o-search-preview` (Chat Completions) - web search/data gathering (Turns 1+2, competitor research)
  - `gpt-5` (Responses API) - UI content generation, mixed language detection, YouTube validation
- **Playwright** - Headless browser for Pillar 1 crawler and cookie banner detection
- **DataForSEO OnPage API** - Site crawl for Pillar 2
- **Google PageSpeed Insights API** - Performance/SEO scores for Pillar 2
- **YouTube Data API v3** - Channel search and validation for Pillar 4
- **python-dotenv** - Environment variable loading
- **beautifulsoup4** - HTML parsing for BFS crawler (legacy) and YouTube scraping
- **tldextract** - Subdomain language detection in Pillar 1 crawler
- **pdfplumber** - PDF parsing (SEMrush integration stub, not actively used)

### Frontend
- **Next.js App Router** (TypeScript)
- **Tailwind CSS**
- **react-hot-toast** - Toast notifications

### Project Layout
```
powerling-preaudit/
├── backend/
│   ├── .env                        # API keys (gitignored)
│   ├── requirements.txt
│   ├── audit_jobs.db               # SQLite DB (auto-created, gitignored)
│   ├── test_pillar1_gather.py      # Test: Playwright crawler + mixed language check
│   ├── test_pillar4_gather.py      # Test: Pillar 4 reputation pipeline
│   ├── test_prompt.py              # Bare-bones GPT-5 prompt tester
│   └── app/
│       ├── audit.py                # Full pipeline orchestration
│       ├── main.py                 # FastAPI app, DB models, endpoints
│       ├── pillar1_gather.py       # Playwright crawler + GPT-5 mixed language detection
│       ├── pillar4_gather.py       # YouTube API + GPT-5 reputation research
│       ├── website_health.py       # PSI + homepage technical checks orchestration
│       └── dataforseo_crawl.py     # DataForSEO OnPage API crawl
└── frontend/
    └── app/
        ├── layout.tsx
        ├── page.tsx                          # Submission form
        └── audits/
            ├── page.tsx                      # Audit list
            └── [job_id]/
                ├── page.tsx                  # Job status polling + auto-redirect
                └── result/
                    └── page.tsx              # Results dashboard
```

---

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/audits` | Submit a new audit job |
| GET | `/audits/{job_id}` | Poll job status |
| GET | `/audits/{job_id}/result` | Get the full completed report (JSON) |

### POST /audits request body (multipart/form-data)
```
url             string   Client website URL
company_name    string   Client company name
competitor_1    string   Competitor 1 URL
competitor_2    string   Competitor 2 URL
competitor_3    string   Competitor 3 URL
```

### Job Status Flow
```
pending → processing → completed
                    ↘ error
```

---

## Pipeline (audit.py: run_audit)

Fully sequential - no concurrency. All phases run in order.

```
Phase 0: Playwright crawler - client site (pillar1_gather.py)
  └── Extracts: hreflang tags, locale URLs, language selector type, cookie banner (CMP provider)
  └── Followed by: GPT-5 mixed language check across locale pages

Phase 0b: Website health data (website_health.py)
  ├── Google PSI: homepage mobile + desktop
  ├── DataForSEO OnPage crawl (up to 200 pages)
  └── Homepage technical checks (robots.txt, sitemap, HSTS, schema, H1)

Phase 1: Client data gathering - 2 independent GPT calls (gpt-4o-search-preview)
  ├── Turn 1: Globalization - geographic presence, required languages, traffic, regional sites
  │           Crawler facts injected as authoritative (available_languages, hreflang, locale_urls)
  │           GPT only fills in what crawler can't: geographic_presence, required_languages, traffic
  └── Turn 2: Accessibility & Compliance - independent call, no Turn 1 history
              Cookie banner injected as authoritative fact (Playwright-detected)

Phase 1b: Online reputation (pillar4_gather.py)
  ├── Step 1: YouTube Data API v3 channel search + domain validation
  ├── Step 2: GPT-5 validation of ambiguous YouTube candidates (if needed)
  ├── Step 3: Website footer scrape for social links (requests + BeautifulSoup)
  └── Step 4: GPT-5 Responses API full reputation research (web search)

Phase 2: Competitor data (one Playwright crawl + one gpt-4o-search-preview call per competitor)
  └── Crawler provides authoritative available_languages; GPT fills in benchmark data

Phase 3: build_facts_pack - merges all gathered data, computes LCR deterministically

Phase 4 [COMMENTED OUT]: GPT-4o pillar narrative generation
  └── Skipped. PDF export dropped from scope.

Phase 5: GPT-5 generate_ui_content(facts)
  └── Single Responses API call, no web search
  └── Produces: executive_summary, per-pillar headlines/findings/recommendations,
               competitive_landscape, top_recommendations

Return: {"facts": {...}, "ui_content": {...}}
```

---

## Key Design Decisions

- **gpt-4o-search-preview** for web search tasks - hard 6000 TPM cap per request, so Turn 1 and Turn 2 are separate independent calls (not stateful) to avoid hitting the ceiling on large sites (64+ hreflang tags)
- **gpt-5 Responses API** for UI content generation and mixed language detection - better reasoning, no TPM ceiling issue for these tasks
- **Playwright as ground truth** - crawler-detected values always override GPT-inferred values. GPT fills in what the crawler cannot (geographic presence, required languages, traffic)
- **Cookie banner via Playwright** - detects 9+ CMPs by script src URL, style tag IDs, window globals, and DOM elements. GTM-loaded CMPs get a 2.5s wait after page load. Injected into Turn 2 as authoritative fact.
- **Turn 1 response schema** - only asks GPT to return fields it actually researches. All crawler-owned fields (hreflang_tags, locale_urls, available_languages, etc.) are excluded to prevent JSON truncation on large sites.
- **LCR computed deterministically** from crawler-confirmed available_languages and GPT-inferred required_languages
- **Phase 4 commented out** - GPT-4o pillar narrative generation not called. PDF export was dropped from scope; UI content comes directly from GPT-5 facts pack synthesis.

---

## Running the App

### Backend
```bash
cd backend
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --reload
# Runs on http://localhost:8000
```

**Important:** If you change the DB schema, delete the DB first:
```bash
rm backend/audit_jobs.db
```

### Frontend
```bash
cd frontend
npm install
npm run dev
# Runs on http://localhost:3000
```

### Required environment variables (backend/.env)
```
OPENAI_API_KEY=...
GOOGLE_PAGESPEED_API_KEY=...
DATAFORSEO_LOGIN=...
DATAFORSEO_PASSWORD=...
YOUTUBE_API_KEY=...   # same key as GOOGLE_PAGESPEED_API_KEY
```

---

## Current State (April 2026)

### What works
- [x] Form submission (company name, URL, 3 competitor URLs)
- [x] Job creation and persistence in SQLite
- [x] Background pipeline execution (pending → processing → completed/error)
- [x] Status polling page with auto-redirect to results on completion
- [x] Playwright crawler: hreflang, locale URLs, language selector, cookie banner detection (9+ CMPs)
- [x] GPT-5 mixed language detection across locale pages
- [x] Pillar 1: Globalization (crawler + GPT research)
- [x] Pillar 2: Website Health (PSI + DataForSEO crawl + homepage checks)
- [x] Pillar 3: Accessibility & Compliance (gpt-4o-search-preview)
- [x] Pillar 4: Online Reputation (YouTube API + GPT-5 web search)
- [x] Competitor data gathering (Playwright + gpt-4o-search-preview per competitor)
- [x] LCR computed deterministically
- [x] GPT-5 UI content generation from facts pack
- [x] Results dashboard (sticky nav, pillar sections, LCR donut, PSI bars, star ratings)
- [x] requirements.txt

### What's missing / not yet done
- [ ] **Competitor name input** - form only takes competitor URLs; company name is GPT-inferred (may be imprecise)
- [ ] **Auth / SSO** - any job is accessible by UUID; SSO integration needed before company-wide rollout (provider TBD). All users see all jobs (shared job list).
- [ ] **Production config** - CORS and frontend API URL hardcoded to localhost; must be env-var-driven before deployment
- [ ] **Multi-user queue** - BackgroundTasks works for single-user; ~40 salespeople may submit concurrently. Design decision: **serialized queue (one job runs at a time, others wait)** to avoid OpenAI rate limit collisions. Implementation: Celery + Redis (AWS ElastiCache). SQLite → PostgreSQL (AWS RDS) also needed for concurrent-safe writes.
- [ ] **Error recovery UI** - failed audits show error state but no retry button

### Explicitly out of scope
- **PDF export** - dropped. UI dashboard is the final deliverable.

---

## Known Issues & Gotchas

- **DB schema changes**: SQLAlchemy's `create_all` won't ALTER existing tables. Must `rm audit_jobs.db` after any model change.
- **gpt-4o-search-preview**: Does not support `response_format={"type": "json_object"}`. JSON enforced via prompt + `_parse_json()` helper.
- **gpt-5 TPM cap**: 6000 TPM per request on web search. Turn 1 was previously stateful (carried Turn 2 context) which caused 429s on large sites. Fixed by making Turn 2 independent.
- **Turn 1 JSON truncation**: On sites with 60+ hreflang tags, GPT would echo back the pre-filled crawler data in its response, causing the JSON to be cut off mid-string. Fixed by removing all crawler-owned fields from the Turn 1 response schema.
- **Cookie banner timing**: GTM-loaded CMPs (banner injected after page load) need a 2.5s `page.wait_for_timeout()` before DOM detection runs.
- **Competitor `company_name`**: Filled in by GPT from its search - may differ slightly from the actual name. Passing competitor names from the form would improve this.
