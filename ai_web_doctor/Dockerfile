# ============================================================================
# AI Web Doctor — Dockerfile
# Multi-stage build:
#   Stage 1 (builder): build the Tailwind CSS bundle with Node.js.
#   Stage 2 (runtime): Python 3.13 + the compiled assets + Playwright Chromium
#                      for the scanner.
# ============================================================================

# --- Stage 1: frontend assets -------------------------------------------------
FROM node:22-alpine AS builder

WORKDIR /app

# Copy only what Tailwind needs to resolve class names.
COPY package.json tailwind.config.js postcss.config.js ./
COPY static/src ./static/src
COPY templates ./templates

RUN npm ci --no-audit --no-fund && npm run build

# --- Stage 2: python runtime ---------------------------------------------------
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System dependencies (PostgreSQL client libs for psycopg + Playwright Chromium).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl ca-certificates fonts-liberation \
       libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdbus-1-3 libdrm2 \
       libgbm1 libglib2.0-0 libnspr4 libnss3 libpango-1.0-0 libx11-6 libxcb1 \
       libxcomposite1 libxdamage1 libxext6 libxfixes3 libxkbcommon0 libxrandr2 \
       xdg-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements ./requirements
RUN pip install --no-cache-dir -r requirements/production.txt

# Install the Playwright Chromium browser used by the scanner.
RUN playwright install chromium \
    && playwright install-deps chromium || true

# Copy application source.
COPY . .

# Copy the Tailwind-built stylesheet from the builder stage.
COPY --from=builder /app/static/css/site.css ./static/css/site.css

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
