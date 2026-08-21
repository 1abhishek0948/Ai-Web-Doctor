# 🔍 AI Web Doctor

**Find broken UI before your users do.**

AI Web Doctor scans real websites in a real browser (Playwright + Chromium), detects responsive,
accessibility, typography, color, spacing, interaction, performance and UX problems with
**deterministic measurements**, uses **AI for analysis and fix suggestions** (text-only by
default), and objectively **verifies** whether a fix actually solved the problem.

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.2%20LTS-092E20?logo=django&logoColor=white)](https://www.djangoproject.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/1abhishek0948/Ai-Web-Doctor/ci.yml?branch=main&logo=github&label=CI)](https://github.com/1abhishek0948/Ai-Web-Doctor/actions)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](docker-compose.yml)

> Everything meaningful about a problem is verified by deterministic re-measurement — never by
> asking an AI whether it looks fixed.

---

## 🌐 Live Demo

**[https://ai-web-doctor.onrender.com](https://ai-web-doctor.onrender.com)**

Hosted on Render's free tier — the first request after idle may take up to a minute to cold-start.

To run it yourself, jump to [Installation](#-installation).

---

## 📖 Overview

Responsive bugs, clipped text, invisible content, tiny tap targets and accessibility violations
routinely reach production because manually checking a site at every screen size is tedious and
error-prone. AI Web Doctor automates that check:

- **What problem it solves** — it loads your website in a real headless browser, measures it at
  nine screen sizes from small phones to desktop, and produces a prioritized, evidence-backed
  report of what is broken, why it matters, and how to fix it.
- **Who it is for** — front-end developers, freelancers and small teams who ship web UI without a
  dedicated QA or design-review pipeline.
- **Why it is useful** — every finding carries pixel-level evidence (overflow in px, element
  boxes, computed styles, axe rule IDs), each issue includes an AI-written diagnosis and an
  on-demand code fix suggestion, and the **Verify Fix** workflow re-measures the live site to
  confirm your fix worked. A transparent **UI Health Score (0–100)** summarizes the result.

The core design principle: **deterministic checks establish measurable facts; AI only explains
and suggests.** AI failures never break a scan, and AI never invents measurements.

---

## ✨ Key Features

### Real browser scanning
Scans run in headless **Chromium** driven by **Playwright** — pages fully load, network settles,
and layout is measured as a real user would see it. Not a DOM-only lint. In production the scan
runs in a short-lived subprocess so Chromium memory is released after every scan and a renderer
crash can never take down the web process.

### 9-viewport responsive testing
Every scan tests nine viewports by default (configurable via `SCAN_VIEWPORTS`):

| Mobile | | Tablet | | Desktop |
|---|---|---|---|---|
| 320 × 800 | 375 × 812 | 600 × 960 | 768 × 1024 | 1024 × 1366 |
| 390 × 844 | 414 × 896 | | 834 × 1112 | 1440 × 900 |

### Responsive & layout issue detection (deterministic)
Per-viewport checks with pixel evidence:

- **Horizontal overflow** — document wider than the viewport (measured in px)
- **Elements outside viewport** — visible elements extending past the edges
- **Text overflow** — text clipped or spilling out of its container
- **Navigation overflow** — unusable/clipped navigation at narrow widths
- **Broken images** and **images missing `alt` text**

### Visual-design analysis (deterministic)
Runs once per scan at the desktop viewport — no AI involved:

- **Typography** — body text under 12px; pages with no coherent type scale (>14 distinct font sizes)
- **Color** — text rendered in the same color as its background (invisible content)
- **Spacing** — same-parent siblings overlapping by more than 8px
- **Interaction** — click targets smaller than 44×44px; clickable controls without a pointer cursor
- **Performance** — images missing `width`/`height` (layout-shift risk); intrinsically oversized images (>2 MP)
- **UX** — vague link labels ("click here", "read more"…); links with no accessible label;
  `target="_blank"` links missing `rel="noopener"`

### Accessibility testing (WCAG)
An **axe-core 4.10** pass runs against WCAG 2.0/2.1 AA rules (`wcag2a`, `wcag2aa`, `wcag21aa`),
with axe impact levels mapped to report severities. Violations include rule ID, help URL, tags,
selector and HTML snippet evidence.

### AI visual analysis & issue explanations
Optional **Gemini** analysis reads the deterministic findings plus DOM structure and adds
reasoning: hierarchy, spacing, alignment, typography, CTA visibility, responsive behavior.
Findings merge into existing issues (deduplicated) or appear as new AI-sourced issues — always
labeled by source.

### Code fix suggestions
For any issue, click **Generate Fix** to get a focused code snippet (CSS / HTML / JavaScript /
JSX) with an explanation and the recommended change. Fixes are **suggestions only** — they are
never executed or auto-applied.

### Verify Fix workflow
After applying a fix, re-run the exact deterministic check that flagged the issue and compare
before/after measurements objectively: `verified` / `improved` / `failed`, with before/after
screenshots stored alongside the verdict.

### UI Health Score
A transparent 0–100 score across six weighted category groups, with identical defects counted
once regardless of how many viewports re-detected them. See [UI Health Score](#-ui-health-score).

### Scan history & accounts
Anonymous visitors can scan immediately (rate-limited per IP). Creating a free account links
scans to your account, unlocks `/scans/` history, and enables password management. All of it is
optional — the scanner works without logging in.

### Operations & observability
Live scan progress via HTMX polling, stale-scan recovery after crashes/deploys, worker
heartbeats, structured JSON event logging, daily rate limits, concurrency caps, and resource
limits on redirects, response size, screenshots and AI payloads.

---

## ⚙️ How It Works

```
URL
↓
Security validation (SSRF guard, DNS resolution check)
↓
Dispatch (DB-polling worker ▸ subprocess ▸ Celery ▸ dev thread)
↓
Playwright — real Chromium loads the page
↓
Multi-viewport capture — 9 viewports: metrics + DOM snapshot + screenshot
↓
Deterministic checks — responsive + layout + navigation (every viewport)
↓
Visual-design checks — typography, color, spacing, interaction, performance, UX (desktop)
↓
axe-core accessibility pass (WCAG 2.0/2.1 AA)
↓
Gemini analysis (text-only, token-budgeted, schema-constrained; optional)
↓
Issue normalization + deduplication
↓
UI Health Score
↓
Developer applies fix
↓
Verify Fix — same deterministic check re-run, before/after compared
```

**Design principle**

- **Deterministic checks establish measurable facts.** Every one of the ten report categories is
  analyzed by deterministic checks, so a clean card means *clean*, never *unchecked*.
- **AI is used for analysis and suggestions only.** It reads the findings and explains *why*
  something looks off and *how* to fix it. AI never reports measurements, and AI failures never
  break the scan.
- **Fix verification is objective.** After a developer applies a suggested fix, the same
  deterministic check that flagged the problem is re-run, producing `verified` / `improved` /
  `failed` with before/after screenshots.

---

## 🏗️ Architecture

```mermaid
flowchart TD
    U[User browser] -->|POST /scans/| W[Django web layer<br/>auth · rate limit · concurrency cap]
    W -->|queues scan| PG[(PostgreSQL<br/>scans · issues · verifications<br/>+ the queue itself)]
    D{Dispatch mode}
    W --> D
    D -->|SCAN_WORKER_MODE| WK[DB-polling worker instance<br/>manage.py scan_worker]
    D -->|SCAN_SUBPROCESS_MODE prod default| SP[Short-lived subprocess<br/>python -m scanner.run]
    D -->|Celery + Redis optional| CE[Celery worker]
    WK --> PW[Playwright + Chromium]
    SP --> PW
    CE --> PW
    PW --> SC[Scanner engine]
    SC --> R[Responsive checks]
    SC --> V[Visual-design checks]
    SC --> AX[axe-core]
    SC --> AI[Gemini text analysis]
    SC --> PG
    AI --> PG
    U -->|HTMX polls| W
    U -->|Verify Fix / Generate Fix| W
```

| Component | Responsibility |
|---|---|
| **Browser (UI)** | Landing page with scan form, live progress polling, results dashboard, issue detail + fix + verify |
| **Django (web)** | Auth, rate limiting, concurrency cap, views, health API, admin, scan queueing |
| **Scan dispatcher** | Prefers DB-polling worker → subprocess → Celery → dev thread; the web process never scans synchronously |
| **Worker / subprocess** | Claims queued scans and runs Chromium in isolation; watchdog kills wedged scans; heartbeat for liveness |
| **PostgreSQL** | Scans, issues, verifications, screenshots metadata, page metrics — also carries the scan queue (no Redis required) |
| **Playwright engine** | Real Chromium lifecycle, shared-page multi-viewport resizing, CDP resource blocking, low-memory flags |
| **Deterministic scanner** | Overflow / outside-viewport / text / image / navigation checks with pixel evidence |
| **Visual-design checks** | Typography, color, spacing, interaction, performance, UX checks |
| **axe-core** | Accessibility rule pass (WCAG 2.0/2.1 AA) |
| **Gemini** | Text analysis + fix generation, Pydantic-schema-constrained, token-budgeted |

Key modules in `scanner/`:

| Module | Purpose |
|---|---|
| `security.py` | SSRF guard: scheme allowlist, private/metadata IP blocking, DNS-resolution checks, redirect-hop validation |
| `browser.py` | Playwright session, low-memory Chromium launch flags, CDP font/media/image blocking |
| `analyzer.py` | Multi-viewport orchestration, friendly error mapping, partial-result handling |
| `responsive.py` | Horizontal overflow, outside-viewport, text overflow, image, navigation checks |
| `visual.py` | Typography, color, spacing, interaction, performance, UX checks |
| `accessibility.py` | axe-core injection (3 CDN fallbacks) and violation normalization |
| `screenshots.py` | JPEG capture + downscaling within size caps |
| `run.py` | Subprocess entry point with hard `os._exit` watchdog |
| `dom.py` / `findings.py` | DOM metrics/snapshots and the normalized finding shape |

---

## 🧰 Technology Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.12+ · Django 5.2 LTS · Django REST Framework · django-environ |
| **Database** | PostgreSQL (psycopg 3) — also carries the scan queue; SQLite fallback for local dev |
| **Async / queue** | DB-polling worker (`manage.py scan_worker`) · short-lived subprocess mode · Celery 5 + Redis (optional) |
| **Browser automation** | Playwright 1.49 · headless Chromium (low-memory launch flags, CDP resource blocking) |
| **Accessibility** | axe-core 4.10 (WCAG 2.0/2.1 AA rules) |
| **AI** | Google Gemini REST API (`httpx`, no SDK) · OpenRouter as an alternative provider · Pydantic v2 output schemas |
| **Frontend** | Tailwind CSS 3.4 · HTMX 2 · Alpine.js 3 · inline Lucide-style SVG icons · highlight.js (fix snippets) |
| **Authentication** | Django `django.contrib.auth` (register, login/logout, password reset/change) |
| **Production server** | Gunicorn · WhiteNoise · ManifestStaticFilesStorage |
| **Deployment** | Render (Blueprint `render.yaml`) · Docker + docker-compose · GitHub Actions CI |

---

## 📁 Project Structure

```
ai_web_doctor/
├── apps/
│   ├── accounts/        # Registration view; Django auth URLs/templates
│   ├── scans/           # Scan model, views, dispatch, rate limiting,
│   │                    # scoring, categories, scan_worker command, health API
│   ├── issues/          # Issue + Verification models, verify-fix services
│   ├── ai/              # Gemini/OpenRouter providers, prompts, Pydantic
│   │                    # schemas, payload sizing, analysis + fix services
│   ├── seo/             # robots.txt, sitemap.xml, no-index middleware, JSON-LD data
│   └── reports/         # Placeholder app (report downloads — planned)
├── config/
│   ├── settings/        # base.py / development.py / production.py
│   ├── celery.py        # Celery app (optional broker-based queue)
│   ├── urls.py          # Root URLconf
│   └── logging_config.py # JSON formatter + log_event() helper
├── scanner/             # Headless scanning engine (browser, security,
│                        # responsive, visual, accessibility, run/watchdog)
├── templates/
│   ├── pages/           # landing, scans, scan_detail, results, issue_detail
│   ├── partials/        # scan_progress, fix_result, verify_result, icons
│   ├── registration/    # login, password reset/change
│   └── ...              # base.html, error pages (400/403/404/429/500), sitemap
├── static/
│   ├── src/input.css    # Tailwind source (rebuild with npm run build)
│   ├── css/site.css     # Compiled bundle (generated)
│   └── vendor/          # Vendored alpine.min.js, htmx.min.js
├── tests/               # Django test suite (14 modules)
├── scripts/             # smoke_prod.sh, generate_seo_assets.py
├── docs/                # PRODUCTION.md (Render + managed Postgres guide)
├── requirements/        # base.txt / development.txt / production.txt
├── .env.example         # Annotated environment template
├── render.yaml          # Render Blueprint (free-tier deployment)
├── Dockerfile           # Multi-stage: Node Tailwind build → Python + Chromium
├── docker-compose.yml   # db + redis + web + celery worker
└── .github/workflows/ci.yml
```

---

## 🚀 Installation

Requirements: **Python 3.12+**, **PostgreSQL 16** (or SQLite for a quick start), **Node.js 22**
(for the Tailwind bundle), and Playwright's Chromium for full scans.

```bash
# 1. Clone
git clone https://github.com/1abhishek0948/Ai-Web-Doctor.git
cd Ai-Web-Doctor

# 2. Virtual environment
python3 -m venv .venv && source .venv/bin/activate

# 3. Python dependencies
pip install -r requirements/development.txt

# 4. Frontend toolchain (builds static/css/site.css)
npm install
npm run build

# 5. Playwright browser
playwright install chromium

# 6. Environment
cp .env.example .env          # then edit DATABASE_URL, SECRET_KEY, GEMINI_API_KEY

# 7. Database (PostgreSQL example)
createdb ai_web_doctor

# 8. Migrations + superuser
python manage.py migrate
python manage.py createsuperuser

# 9. Run
python manage.py runserver
```

Visit **http://127.0.0.1:8000** — the landing page has the scan form. Paste a **public** URL;
localhost/private hosts are blocked by the SSRF guard, so use live public sites (or exercise the
scanner directly from a shell for local development).

> No `DATABASE_URL`? The app falls back to SQLite (`db.sqlite3`) automatically.

### Background scan execution

By default in development (`CELERY_TASK_ALWAYS_EAGER=True`) scans run in a background thread —
no extra services needed. For a real queue:

```bash
# Option A: DB-polling worker (no Redis needed — the production-style setup)
python manage.py scan_worker            # in a second terminal

# Option B: Celery (requires Redis)
export REDIS_URL=redis://localhost:6379/0
export CELERY_TASK_ALWAYS_EAGER=False
celery -A config.celery worker --concurrency 1 --loglevel=info
```

### Docker

```bash
docker compose up --build               # db + redis + web + celery worker
docker compose exec web python manage.py createsuperuser
```

---

## 🔐 Environment Variables

Copy `.env.example` to `.env` and fill in real values. Never commit `.env`.

### Core

| Variable | Default | Purpose |
|---|---|---|
| `DEBUG` | `False` | Enable only in development |
| `SECRET_KEY` | — | Django secret (required in production) |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated host list |
| `CSRF_TRUSTED_ORIGINS` | `[]` | Origins trusted for POST (e.g. `https://your-host`) |
| `SITE_URL` | `http://localhost:8000` | Canonical URL for OG tags / sitemap |
| `DATABASE_URL` | SQLite fallback | e.g. `postgres://user:pass@host:5432/dbname` |

### Scan execution

| Variable | Default | Purpose |
|---|---|---|
| `SCAN_WORKER_MODE` | `False` (`True` if set) | Queue scans for `manage.py scan_worker` |
| `SCAN_SUBPROCESS_MODE` | `False` (`True` in prod) | Run scans in a short-lived subprocess |
| `CELERY_TASK_ALWAYS_EAGER` | `True` unless broker set | Dev fallback: run scans in a thread |
| `REDIS_URL` / `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | empty | Only for the Celery queue |
| `MAX_CONCURRENT_SCANS` | `2` (forced `1` in prod) | Concurrent in-flight scans |
| `MAX_SCAN_DURATION` | `120` | Seconds before a scan skips AI and wraps up |
| `SCAN_MAX_DURATION_SECONDS` | `300` | Hard kill deadline for the scan subprocess watchdog |
| `SCAN_VIEWPORTS` | 9 defaults | JSON pairs, e.g. `[[320,800],[768,1024],[1440,900]]` |
| `PLAYWRIGHT_HEADLESS` | `True` | Run Chromium headless |
| `SCAN_PAGE_TIMEOUT_MS` | `30000` | Navigation timeout |
| `SCAN_NETWORK_IDLE_TIMEOUT_MS` | `1500` | Bounded network-idle wait per viewport |
| `MAX_REDIRECTS` | `5` | Redirect budget during navigation |
| `MAX_RESPONSE_SIZE` | `5242880` | Max response body bytes |
| `MAX_SCREENSHOTS` | `16` | Screenshots stored per scan |
| `MAX_SCREENSHOT_SIZE` | `8388608` | Max bytes per screenshot (oversized shots downscaled) |
| `SCAN_AXE_VIEWPORTS` | `desktop` | `desktop` = axe on desktop viewport only; `all` = every viewport |
| `SCAN_DOM_SNAPSHOT_LIMIT` | `80` | Elements captured per DOM snapshot |
| `CHROMIUM_LOW_MEMORY_MODE` | `True` | Capped V8 heaps, no background services |
| `CHROMIUM_V8_HEAP_MB` | `144` | V8 old-space heap cap (MB) |
| `SCAN_BLOCK_HEAVY_RESOURCES` | `True` | Abort fonts/media/tracker requests via CDP |
| `SCAN_BLOCK_IMAGES` | `False` | Also abort image requests (extreme low-memory mode) |

### AI

| Variable | Default | Purpose |
|---|---|---|
| `AI_ENABLED` | `True` | Master switch for AI features |
| `AI_PROVIDER` | `gemini` | `gemini` or `openrouter` |
| `GEMINI_API_KEY` | empty | Gemini API key (AI is optional without it) |
| `GEMINI_MODEL` | `gemini-3.6-flash` | Model used for analysis/fixes (fallback candidates tried on 404) |
| `GEMINI_TIMEOUT_MS` | `60000` | Per-attempt request timeout |
| `GEMINI_MAX_RETRIES` | `2` | Retries before analysis/fix fails |
| `OPENROUTER_API_KEY` | empty | OpenRouter key (alternative provider) |
| `OPENROUTER_MODEL` | *(see .env.example)* | OpenRouter model id |
| `OPENROUTER_TIMEOUT_MS` / `OPENROUTER_MAX_RETRIES` | `120000` / `2` | OpenRouter tuning |
| `AI_SEND_IMAGES` | `False` | Text-only analysis by default; `True` attaches screenshots (much higher token usage) |
| `AI_MAX_PROMPT_TOKENS` | `15000` | Hard cap on prompt text tokens per request |
| `AI_IMAGE_MAX_WIDTH` / `AI_IMAGE_QUALITY` | `1024` / `70` | Screenshot optimization when images enabled |

### Rate limiting & security

| Variable | Default | Purpose |
|---|---|---|
| `RATE_LIMIT_ANONYMOUS_SCANS_PER_DAY` | `20` | Daily quota per IP (anonymous) |
| `RATE_LIMIT_AUTHED_SCANS_PER_DAY` | `10` | Daily quota per account |
| `TRUST_X_FORWARDED_FOR` | `False` | Set `True` only behind a trusted reverse proxy |
| `LOG_LEVEL` | `INFO` | Root log level |

### Production extras (`config/settings/production.py`)

`SECURE_SSL_REDIRECT` (default `True`), `SESSION_COOKIE_SECURE` (`True`), `CSRF_COOKIE_SECURE`
(`True`), `SECURE_HSTS_SECONDS` (`3600`), `SECURE_HSTS_INCLUDE_SUBDOMAINS` (`True`),
`SECURE_HSTS_PRELOAD` (`True`), plus SMTP email settings (`EMAIL_BACKEND`, `EMAIL_HOST`,
`EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`,
`DEFAULT_FROM_EMAIL`) for password reset emails.

---

## 🖱️ Usage

1. **Open the app** — the landing page has a scan form. No account required.
2. **Enter a public URL** (e.g. `https://example.com`) and click **Scan Website**.
3. **Watch live progress** — you're redirected to the scan page, which polls through stages:
   validating URL → launching browser → loading website → capturing screenshots → checking
   responsive layout → checking accessibility → running AI analysis → building report.
4. **Open the results dashboard** — see the UI Health Score with its per-group breakdown,
   issue counts by severity, ten diagnostic category cards (each labeled *Analyzed* /
   *Not analyzed*), filterable issue list, and viewport screenshots.
5. **Inspect an issue** — click any issue for severity, category, source badge
   (deterministic / accessibility / AI / combined), pixel evidence, element selector, relevant
   markup, the matching screenshot, and the AI diagnosis when available.
6. **Generate a fix** — click **Generate Fix** for an AI-written explanation, recommended
   change, and code snippet (CSS/HTML/JS/JSX). Copy it, review it, apply it in your codebase.
7. **Verify Fix** — after deploying your fix, click **Verify Fix**. The scanner reloads the
   site at that issue's viewport, re-runs the same deterministic check, and shows
   `verified` / `improved` / `failed` with before/after measurements and screenshots.
8. **Track history (optional)** — create a free account to link scans to your account and
   revisit them under `/scans/`.

---

## 📊 UI Health Score

The score is computed entirely from persisted issues and scan state — nothing hardcoded
(`apps/scans/scoring.py`):

**Severity penalties** (deducted per root defect):

| Severity | Penalty |
|---|---|
| Critical | −12 |
| High | −6 |
| Medium | −3 |
| Low | −1 |
| Info | 0 |

**Category group weights** (sum to 100):

| Group | Weight | Raw categories included |
|---|---|---|
| Responsive | 25 | responsive |
| Accessibility | 20 | accessibility |
| Visual | 20 | spacing, color, interaction, performance |
| Layout | 15 | layout |
| Typography | 10 | typography |
| UX | 10 | navigation, ux |

**Rules:**

- Issues collapse into **root defects**: same category + same check/rule + same element counts
  **once**, at its highest severity — so detecting the same broken image at 9 viewports costs
  one penalty, not nine.
- Each group scores `max(0, weight − total_penalty)`; group scores sum into the total.
- The result is normalized by the weight actually analyzed (`earned / analyzed_weight × 100`),
  so a clean completed scan scores exactly 100 and a failed scan has no score at all.
- Every category is covered by deterministic checks on every completed scan, so full coverage is
  the norm; AI findings simply enrich the same categories.

The results page exposes the full computation ("How this score is computed") with per-group
weights, defect counts and penalties.

---

## 🧪 Detection System

### Deterministic checks (always run, no AI)

Pure in-browser measurements via computed styles and bounding boxes. Each finding carries a
stable shape: `check`, `category`, `title`, `severity`, `viewport`, `description`, `selector`,
`evidence`, `confidence: 1.0`.

| Check | Category | Trigger |
|---|---|---|
| `horizontal_overflow` | responsive | `scrollWidth > innerWidth` |
| `element_outside_viewport` | responsive | Visible element box beyond viewport edges |
| `text_overflow` | layout | Element clips its own content ≥3px |
| `broken_image` | layout | `naturalWidth === 0` on a loaded `<img>` |
| `missing_image_alt` | accessibility | `<img>` without `alt` attribute |
| `navigation_overflow` | navigation | `nav`/`header`/[role=navigation] overflows |
| `tiny_text` | typography | Visible text < 12px |
| `font_scale_inconsistency` | typography | > 14 distinct font sizes |
| `invisible_text` | color | Text color equals background color |
| `overlapping_siblings` | spacing | Same-parent siblings overlap > 8px |
| `small_touch_target` | interaction | Clickable target < 44×44px |
| `missing_pointer_cursor` | interaction | Clickable control without pointer cursor |
| `missing_image_dimensions` | performance | `<img>` without width/height attributes |
| `oversized_image` | performance | Intrinsic image > ~2 MP |
| `generic_link_text` | ux | Labels like "click here", "read more" |
| `empty_link` | ux | Anchor with no text/title/aria-label |
| `blank_target_without_rel` | ux | `target="_blank"` without `rel="noopener"` |

### AI-based checks (optional enrichment)

Gemini receives the deterministic findings summary + DOM structure summary (text-only by
default) and returns schema-validated UX findings: likely cause, recommendation, confidence.
AI findings either **merge into matching deterministic/accessibility issues** (same category +
viewport + significant text overlap → source becomes `combined`) or are added as new `ai`-source
issues. Invalid individual findings are skipped leniently; one bad issue never invalidates the
whole response.

---

## ♿ Accessibility

- **Tool:** axe-core 4.10, injected into the scanned page from three CDN fallbacks
  (jsDelivr → unpkg → cdnjs) with graceful degradation — if axe can't load (CSP, offline),
  accessibility findings are omitted and the rest of the scan proceeds.
- **Rule sets:** `wcag2a`, `wcag2aa`, `wcag21aa`.
- **Severity mapping:** axe impact → report severity (critical→critical, serious→high,
  moderate→medium, minor→low).
- **Evidence retained:** rule ID, impact, help URL, WCAG tags, affected node count, CSS
  selector, HTML snippet.
- **Complementary deterministic checks:** missing image alt text, empty/unlabeled links, small
  touch targets, and vague link labels are also caught deterministically and deduplicated
  against axe results.
- **Viewport policy:** by default axe runs on the desktop viewport only in low-memory mode
  (`SCAN_AXE_VIEWPORTS=desktop`); set `all` for per-viewport coverage.

---

## 🤖 AI Integration

- **Providers:** Gemini (default) via the `generateContent` REST endpoint using `httpx`; OpenRouter
  as a drop-in alternative selected by `AI_PROVIDER`. Keys travel in headers
  (`x-goog-api-key`, with an `Authorization: Bearer` fallback) — never in URLs or logs.
- **Model fallback:** if the configured model returns 404, the provider automatically tries
  `gemini-2.5-flash` → `gemini-2.0-flash` → `gemini-1.5-flash` → `gemini-2.0-flash-lite`.
- **Responsibilities:** post-scan visual/UX analysis (hierarchy, spacing, alignment, typography,
  CTA visibility, responsive behavior) and on-demand fix generation. AI never performs
  measurements and never gates the scan.
- **Payload:** text-only by default (`AI_SEND_IMAGES=False`) — deterministic findings + DOM
  structure summary, capped by `AI_MAX_PROMPT_TOKENS` (~4 chars/token heuristic). When images
  are enabled, representative viewports (mobile/tablet/desktop) plus viewports with critical/high
  findings are attached as optimized JPEGs, dropping largest-first until the payload fits
  `MAX_AI_REQUEST_SIZE`.
- **Structured output:** responses are constrained by a generation schema and validated with
  Pydantic models (`AIIssue`, `AIAnalysis`, `AIFix`); alternate field names the model emits are
  normalized leniently.
- **Timeout/retry:** per-attempt timeout (`GEMINI_TIMEOUT_MS`) with linear backoff, up to
  `GEMINI_MAX_RETRIES` retries. Rate-limit (429/quota) and auth (401/403) errors stop retrying
  immediately.
- **When AI is unavailable:** the scan records a machine-readable `ai_status`
  (`unavailable` / `failed` / `rate_limited` / `skipped`) plus a human-friendly message on the
  results page. Deterministic results and the health score are unaffected. If the scan has
  already consumed its time budget, AI is skipped rather than delaying completion.

---

## 🩺 Fix & Verify

This is the feature that closes the loop from detection to confirmed repair.

**1. Identifying the problematic element**
Deterministic findings capture the offending element's tag/id/classes, bounding box, computed
styles and relevant markup snippet; axe violations carry the CSS selector target and node HTML.
Everything is persisted as evidence on the Issue row.

**2. Generating the explanation**
During analysis, Gemini explains *why* the measured condition is a problem (stored as
`ai_explanation`: likely cause + recommendation). Even without AI, every deterministic issue
ships a plain-language description with exact numbers ("document is 1280px wide but the viewport
is only 375px").

**3. Providing the recommended fix**
Clicking **Generate Fix** builds a focused prompt from the issue summary, its evidence and the
relevant element HTML, and asks the model for a strict JSON response: `explanation`,
`recommended_change`, `code`, `language` (CSS/HTML/JavaScript/JSX). The snippet is displayed
with syntax highlighting and a copy button. It is a **suggestion only** — never executed,
injected into the scanned site, or deployed.

**4. Verifying whether the fix resolved the issue**
Clicking **Verify Fix** reloads the live site in a fresh browser at the issue's original
viewport, re-runs the *exact same deterministic check* that flagged the problem (axe rules too,
for accessibility issues), and matches the original element by selector:

| Verdict | Meaning |
|---|---|
| `verified` | Measurement gone (e.g. overflow 42px → 0px) |
| `improved` | Measurement shrank but the problem remains (42px → 8px) |
| `failed` | Unchanged or worse |

Before/after screenshots are stored with the verdict, and the comparison message shows both
values ("Horizontal overflow is no longer detected (42px -> 0px)"). Issues without an objective
measurement say so explicitly instead of pretending to verify.

---

## 🚢 Deployment

### Render (current production setup)

The repo ships a Render Blueprint (`render.yaml`) for one-click free-tier deployment:

- **Web service** — Docker runtime; gunicorn + WhiteNoise serve the app and static files.
- Free tier has no background workers, so production defaults to **subprocess mode**
  (`SCAN_SUBPROCESS_MODE=True`): each scan spawns a short-lived child process running Chromium;
  all browser memory is released when it exits, and an OOM in the child never kills gunicorn.
  Concurrency is forced to 1 and memory-saving Chromium flags keep peak RSS inside the 512 MB
  container.
- A **Pre-Deploy Command** of `python manage.py migrate --noinput` applies migrations.
- If your plan supports background workers, set `SCAN_WORKER_MODE=True` and run
  `python manage.py scan_worker` on a dedicated worker service instead — the DB-polling worker
  needs no broker.
- `docs/PRODUCTION.md` documents a hardened variant using managed **Aiven PostgreSQL** and
  **Upstash Redis** (Celery mode), including required env vars and first-deploy steps.
- Post-deploy smoke test: `BASE_URL=https://your-app.onrender.com scripts/smoke_prod.sh`
  (checks `/api/health/`, submits a real scan of example.com, and polls to completion).

### Docker

`Dockerfile` is a multi-stage build: Node 22 compiles the Tailwind bundle, then Python 3.13-slim
installs dependencies and Playwright Chromium with malloc tuned for small containers.
`docker-compose.yml` brings up Postgres 16, Redis 7, the web service and a Celery worker.

### Production hardening

`config/settings/production.py` enforces `DEBUG=False`, requires `SECRET_KEY`, enables SSL
redirect, secure cookies, HSTS (+preload), `SECURE_PROXY_SSL_HEADER`, WhiteNoise middleware and
`ManifestStaticFilesStorage`. `python manage.py check --deploy` passes clean.

---

## 🧬 Testing

```bash
python manage.py test            # full suite
python manage.py check --deploy  # deployment security checks
```

The suite (in `tests/`) covers: verification logic + service + views, UI Health scoring and
category mapping, deterministic visual checks, AI service (payload building, merging, error
handling), AI status surfacing, issue queries, results dashboard, landing page, SEO endpoints,
stale-scan recovery, rate limiting, production hardening, and the health endpoint. Browser work
is mocked — no Chromium needed to run tests.

CI (`.github/workflows/ci.yml`) runs on push/PR to `main`: installs Python 3.12 + Node 22
dependencies against a Postgres 16 service, builds the Tailwind bundle, runs `manage.py check`
and the full test suite.

---

## 🛡️ Security

- **SSRF protection** — every target URL (and every redirect hop) is validated: only http/https
  schemes allowed; localhost, RFC1918/private, loopback, link-local, reserved and multicast IPs
  rejected; cloud-metadata endpoints blocked; internal hostname suffixes (`.local`, `.internal`,
  `.home.arpa`, `.lan`, `.corp`) rejected; DNS is resolved and every address checked before
  navigation (narrowing DNS-rebinding exposure).
- **Secrets management** — all credentials come from environment variables; `.env` is
  gitignored (only `.env.example` is committed); API keys are sent in headers, never logged.
- **Rate limiting** — daily scan quotas per IP (anonymous) and per account (authenticated);
  client IP only trusts `X-Forwarded-For` behind an explicitly trusted proxy.
- **Resource limits** — caps on scan duration (soft budget + hard watchdog), concurrent scans,
  redirect count, response size, screenshot size/count, DOM snapshot size and AI payload size.
- **Crash isolation** — scans run in a subprocess (or dedicated worker) so Chromium OOM/crashes
  cannot take down the web process; stale scans are swept so slots never leak.
- **Django hardening** — CSRF middleware on all forms, `X_FRAME_OPTIONS=DENY`, content-type
  nosniff, HSTS + secure cookies + SSL redirect in production, strong password validators,
  friendly error pages with no stack traces, and `ALLOWED_HOSTS` enforced.
- **AI output safety** — model responses validated against strict Pydantic schemas; generated
  fixes are display-only suggestions, never executed.
- **No-index for private data** — scan/report pages send `noindex` headers and are excluded
  from robots.txt and the sitemap.

---

## ⚠️ Limitations

Honest constraints of the current implementation:

- **Public URLs only** — the SSRF guard blocks localhost/private hosts, so you cannot scan
  locally running sites through the web flow.
- **Single-page scans** — the scanner audits the submitted URL only; it does not crawl
  additional pages or require login to view target pages.
- **axe coverage depends on viewport policy** — in low-memory mode the axe pass runs on the
  desktop viewport only by default.
- **AI is best-effort** — without a Gemini/OpenRouter key, or when rate-limited/timed out, AI
  diagnosis and fix suggestions are unavailable; deterministic results still ship.
- **Verification scope** — Verify Fix re-checks only issues with objective measurements
  (overflow, clipping, images, axe rules); purely subjective AI findings cannot be verified.
- **Free-tier media storage** — screenshots/results are stored on local disk, which is ephemeral
  on platforms like Render (files reset on redeploy) unless a persistent disk is attached.
- **Single-page apps** — heavily JS-gated content gets a bounded network-idle wait (~1.5s);
  very slow client-side rendering may be captured mid-load.
- **DNS rebinding** — mitigated by validating every hop immediately before navigation, but not
  fully preventable without connection pinning.
- **Reports app is a placeholder** — downloadable PDF/health-history reports are planned, not
  implemented.
- **API surface is minimal** — only `/api/health/` exists today; there is no public REST API for
  scans/issues yet.

---

## 🗺️ Roadmap

**Shipped today**

- Real-browser multi-viewport scanning with deterministic checks across all 10 categories
- axe-core WCAG accessibility pass
- Gemini text analysis + schema-validated fix suggestions (images optional)
- Objective Verify Fix with before/after evidence
- Transparent UI Health Score with root-defect deduplication
- Accounts, scan history, rate limiting, SSRF guard, structured logging
- Broker-free production architecture (worker/subprocess) deployed on Render

**Planned**

- 📄 Report downloads and health-score history (`apps/reports`)
- 🔌 Public REST API for scans and issues (beyond the health endpoint)
- 🕷️ Multi-page crawling and authenticated scanning
- 📈 Trend dashboards comparing scans over time
- 🔄 CI integration (fail builds on score regressions)

---

## 🤝 Contributing

Contributions are welcome!

1. Open an issue first for significant changes to discuss the approach.
2. Fork the repo and create a feature branch from `main`.
3. Follow the project's design principle: deterministic checks own the facts; AI only explains
   and suggests.
4. Add or update tests for your change.
5. Run the full suite locally and make sure it passes:

   ```bash
   python manage.py test
   python manage.py check --deploy
   ```

6. Open a pull request describing what changed and why.

---

## 📄 License

Released under the [MIT License](LICENSE) © Abhishek Thakur.

---

## 👤 Author

**Abhishek Thakur**

- GitHub: [@1abhishek0948](https://github.com/1abhishek0948/)
- LinkedIn: [abhishek0948](https://www.linkedin.com/in/abhishek0948/)
- Email: 111abhishek.04367@gmail.com

---

<div align="center">

**[AI Web Doctor](https://ai-web-doctor.onrender.com)** — Find broken UI before your users do.

</div>
