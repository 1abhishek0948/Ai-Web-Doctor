# Production deployment guide (Render + Aiven + Upstash)

How to run AI Web Doctor in production on Render using a managed Aiven PostgreSQL
database and an Upstash Redis broker. This document only changes environment
configuration — no application code changes are required.

## 1. Environment variables (Render dashboard)

Set these in the Render dashboard (Service → Environment). Never commit `.env`
or paste credentials into the repository.

| Variable | Value | Notes |
| --- | --- | --- |
| `DEBUG` | `False` | Must be false in production. |
| `SECRET_KEY` | `<random, long, unique>` | Generate with `python -c "import secrets; print(secrets.token_urlsafe(50))"`. |
| `ALLOWED_HOSTS` | `aiwebdoctor.onrender.com` | Comma-separated list. |
| `SITE_URL` | `https://aiwebdoctor.onrender.com` | Used for canonical/OG/sitemap URLs. |
| `DATABASE_URL` | `postgres://avnadmin:<password>@pg-<host>.aivencloud.com:<port>/<dbname>` | Your Aiven PostgreSQL connection string (public endpoint). |
| `REDIS_URL` | `rediss://default:<token>@<host>.upstash.io:6379` | Upstash Redis with TLS. Note the `rediss://` scheme — required. |
| `CELERY_BROKER_URL` | *(optional)* | Defaults to `REDIS_URL`; only set if you want a separate broker. |
| `CELERY_RESULT_BACKEND` | *(optional)* | Defaults to `REDIS_URL`. |
| `CELERY_TASK_ALWAYS_EAGER` | `False` | Do not run scans inline; let the Celery worker execute them. |
| `GEMINI_API_KEY` | `<your key>` | Google Gemini API key. |
| `GEMINI_MODEL` | `gemini-3.6-flash` | Model used for AI visual analysis. |
| `AI_ENABLED` | `True` | Set `False` to disable AI analysis entirely. |
| `TRUST_X_FORWARDED_FOR` | `True` | Required behind Render's proxy so rate limits key on the real client IP. |
| `RATE_LIMIT_ANONYMOUS_SCANS_PER_DAY` | `3` | Optional; defaults exist for all scan limits. |
| `MAX_CONCURRENT_SCANS` | `2` | Optional; matches the default. |

All other settings (viewports, timeouts, screenshot limits) already have
production-appropriate defaults in `config/settings/base.py`.

## 2. Aiven PostgreSQL setup

1. Create a PostgreSQL service in the Aiven console.
2. Enable the **public** endpoint (Render instances cannot reach private-network
   endpoints, and Render free/standard instances use shared dynamic egress IPs).
3. In the service's connection/allowlist settings, add `0.0.0.0/0` if the
   connection is refused — Aiven's default allowlist blocks unknown IPs.
4. TLS is handled automatically: psycopg 3 (installed) uses `sslmode=prefer`
   with standard CA verification. No extra connection options are needed.
5. Copy the connection URI from the Aiven console (it contains the
   `avnadmin` user and password) into `DATABASE_URL`.
   - If the password contains special characters, URL-encode them
     (`@` → `%40`, `#` → `%23`, etc.).
   - Prefer a dedicated database name for this app (e.g. `ai_web_doctor`).

## 3. Upstash Redis setup

1. Create a Redis database in the Upstash console (https://console.upstash.com/).
2. Use the **TLS** connection string — it always starts with `rediss://`
   (not `redis://`). Celery/kombu and redis-py support `rediss://` natively
   (verified with celery 5.4 / redis-py 5.3 / kombu).
3. Paste it into `REDIS_URL`.
4. If the TLS handshake fails (rare, e.g. custom CA setups), append
   `?ssl_cert_reqs=none` to the URL as a fallback.
5. Limits: Upstash free tier caps messages at 1 MB. Scan tasks only carry a
   `scan_id`, so this is fine. Task results are small JSON.

## 4. First deployment steps

The Dockerfile starts gunicorn only — it does **not** run migrations. Run them
once, from a fresh database:

1. Render dashboard → your web service → **Pre-Deploy Command**:
   `python manage.py migrate --noinput`
2. Deploy the service. Then verify:

```bash
# 1. App boots and health endpoint responds
curl -s https://aiwebdoctor.onrender.com/api/health/

# 2. SEO endpoints respond
curl -s https://aiwebdoctor.onrender.com/robots.txt
curl -s https://aiwebdoctor.onrender.com/sitemap.xml

# 3. Run one real scan from the landing page and confirm it completes
#    (scans land in the new Aiven database, reported by the worker)
```

3. Add a **worker service** on Render using the same repository:
   - Start command: `celery -A config worker --loglevel=info`
   - Same env vars as the web service (or a shared env group).
4. Confirm the worker connects to Upstash: the startup log shows the broker
   URL and `ready.` after connecting.
5. Trigger a scan; watch the worker log for `scan_execute` and verify the
   result page renders with issues/score.

## 5. Security notes

- `.env` is gitignored; keep secrets out of the repository and the Render log
  output.
- Keep `DEBUG=False` in production; `manage.py check --deploy` validates
  production hardening (HSTS/SSL flags can be enabled via
  `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, etc. in
  `config/settings/production.py`).
- Screenshots and other media are stored on the local filesystem
  (`MEDIA_ROOT`), not in the database. On Render, either attach a persistent
  disk or accept ephemeral storage (files reset on redeploy). This does not
  affect database data.