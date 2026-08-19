#!/usr/bin/env bash
# ============================================================================
# smoke_prod.sh — post-deploy smoke check for AI Web Doctor.
#
# Usage:
#   BASE_URL=https://ai-web-doctor.onrender.com scripts/smoke_prod.sh
#   scripts/smoke_prod.sh https://ai-web-doctor.onrender.com
#
# Checks:
#   1. /api/health/ responds 200 with {"status": "ok"}
#   2. A real scan of https://example.com completes (polling until terminal)
#   3. AI analysis status is reported (depends on GEMINI_API_KEY being set)
#
# Exit codes: 0 = all good, 1 = health/scan failed, 2 = scan timed out.
# ============================================================================
set -euo pipefail

BASE_URL="${1:-${BASE_URL:-https://ai-web-doctor.onrender.com}}"
COOKIE_JAR="$(mktemp)"
SCAN_URL="https://example.com"
MAX_WAIT=300
POLL_INTERVAL=5

echo "== Smoke check against ${BASE_URL}"

echo "1) Health endpoint..."
HEALTH="$(curl -sS -m 20 "${BASE_URL}/api/health/")"
echo "   ${HEALTH}"
echo "${HEALTH}" | grep -q '"status": *"ok"' || {
  echo "   FAIL: health endpoint not ok" >&2
  exit 1
}

echo "2) Submitting a scan of ${SCAN_URL}..."
CSRF="$(curl -sS -m 30 -c "${COOKIE_JAR}" "${BASE_URL}/" | grep -o 'name="csrfmiddlewaretoken" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"//')"
if [ -z "${CSRF}" ]; then
  echo "   FAIL: could not fetch CSRF token from landing page" >&2
  exit 1
fi
RESPONSE="$(curl -sS -m 30 -b "${COOKIE_JAR}" -c "${COOKIE_JAR}" \
  -X POST "${BASE_URL}/scans/" \
  --data-urlencode "csrfmiddlewaretoken=${CSRF}" \
  --data-urlencode "url=${SCAN_URL}" \
  -H "Referer: ${BASE_URL}/" \
  -o /dev/null -w "%{http_code} %{redirect_url}")"
HTTP_CODE="${RESPONSE%% *}"
REDIRECT="${RESPONSE#* }"
echo "   POST status: ${HTTP_CODE} -> ${REDIRECT}"
if [ "${HTTP_CODE}" != "302" ]; then
  echo "   FAIL: scan submission did not redirect (got ${HTTP_CODE})" >&2
  exit 1
fi

SCAN_ID="$(basename "${REDIRECT}")"
echo "   Scan id: ${SCAN_ID}"

echo "3) Polling scan ${SCAN_ID} for up to ${MAX_WAIT}s..."
DEADLINE=$(( $(date +%s) + MAX_WAIT ))
STATUS="pending"
while [ "$(date +%s)" -lt "${DEADLINE}" ]; do
  PAGE="$(curl -sS -m 30 -b "${COOKIE_JAR}" "${BASE_URL}/scans/${SCAN_ID}/")"
  STATUS="$(echo "${PAGE}" | grep -o 'data-scan-status="[^"]*"' | head -1 | sed 's/.*="//;s/"//')"
  [ -z "${STATUS}" ] && STATUS="pending"
  echo "   status: ${STATUS}"
  case "${STATUS}" in
    completed|failed) break ;;
  esac
  sleep "${POLL_INTERVAL}"
done

echo "4) Verifying result..."
case "${STATUS}" in
  completed)
    echo "   OK: scan completed"
    echo "${PAGE}" | grep -o 'AI analysis: [^<]*' | head -1 \
      && echo "   (set GEMINI_API_KEY on Render to enable AI analysis if it is unavailable)"
    rm -f "${COOKIE_JAR}"
    exit 0
    ;;
  failed)
    echo "   FAIL: scan failed — see ${BASE_URL}/scans/${SCAN_ID}/" >&2
    rm -f "${COOKIE_JAR}"
    exit 1
    ;;
  *)
    echo "   FAIL: scan did not reach a terminal state within ${MAX_WAIT}s" >&2
    rm -f "${COOKIE_JAR}"
    exit 2
    ;;
esac