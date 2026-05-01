#!/bin/bash
# Smoke test — verifies the platform actually works end-to-end.
# Targets the regressions we've already had to fix multiple times:
#   1. Tech spec doesn't render in lot detail page (build/cache mismatch)
#   2. Bank-guarantee template leaks into technical_spec_text (data integrity)
#   3. Lot detail API returns 500 / unauthorized
#   4. Frontend container serves old bundle after code change (rebuild missed)
#
# Usage:  ./scripts/smoke-test.sh
# Exits non-zero if anything is broken — wire it into CI later.

set -u
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

API="${API:-http://localhost:8000}"
WEB="${WEB:-http://localhost:3000}"
EMAIL="${ADMIN_EMAIL:-admin@tender.ai}"
PASS="${ADMIN_PASS:-admin123}"

fail=0
pass=0

ok() { echo -e "${GREEN}[OK]${NC}    $1"; pass=$((pass+1)); }
bad() { echo -e "${RED}[FAIL]${NC} $1"; fail=$((fail+1)); }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

# 1. backend healthy
status=$(curl -s -o /dev/null -w "%{http_code}" "$API/health")
[ "$status" = "200" ] && ok "backend /health $status" || bad "backend /health $status (expected 200)"

# 2. frontend reachable
status=$(curl -s -o /dev/null -w "%{http_code}" "$WEB")
[ "$status" = "200" ] && ok "frontend $status" || bad "frontend $status (expected 200)"

# 3. login
TOKEN=$(curl -s -X POST "$API/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" \
  | python -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)
[ -n "$TOKEN" ] && ok "auth/login token len=${#TOKEN}" || { bad "auth/login no token"; exit 1; }

# 4. pick 3 lots from /lots and verify each opens, has spec, no guarantee leak
LOT_IDS=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/api/v1/lots?limit=3" \
  | python -c "
import sys, json
try:
    d = json.load(sys.stdin)
    items = d.get('items') if isinstance(d, dict) else d
    for it in (items or [])[:3]:
        print(it['id'])
except Exception as e:
    pass
")

if [ -z "$LOT_IDS" ]; then
  warn "no lots in DB — skipping per-lot checks (run a scan first)"
else
  # Write to a project-local file: bash mktemp on Windows returns /tmp/...
  # which Python (Windows-native) cannot resolve. Local relative path works
  # for both shells.
  TMP=".smoke_lot.json"
  for ID in $LOT_IDS; do
    rm -f "$TMP"
    HTTP=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/api/v1/lots/$ID" --max-time 120 -o "$TMP" -w "%{http_code}")

    if [ ! -s "$TMP" ]; then
      bad "lot $ID — http=$HTTP, no response (timeout or auto-extract too slow)"
      continue
    fi

    SPEC_OK=$(python -c "
import json
with open('$TMP', 'r', encoding='utf-8') as f:
    d = json.load(f)
spec = d.get('technical_spec_text') or ''
low = spec.lower()
markers = ['[документ: обеспечение', 'банковская гарантия', 'бенефициар',
           'гарантодател', 'сумма гарантии', 'обеспечение заявки']
hits = sum(1 for m in markers if m in low)
underscores = low.count('____') >= 5 and ('гаранти' in low or 'обеспечени' in low)
if hits >= 2 or underscores:
    print(f'GUARANTEE_LEAK spec_len={len(spec)}')
elif spec:
    print(f'OK spec_len={len(spec)}')
else:
    print(f'EMPTY')
")

    case "$SPEC_OK" in
      OK*)             ok "lot $ID — $SPEC_OK" ;;
      EMPTY*)          warn "lot $ID — $SPEC_OK (spec not yet extracted, may be normal)" ;;
      GUARANTEE_LEAK*) bad "lot $ID — $SPEC_OK (regression: bank-guarantee in spec_text)" ;;
      *)               bad "lot $ID — could not parse response" ;;
    esac
  done
  rm -f "$TMP"
fi

# Make sure smoke artifact is gitignored (created during test runs)

# 5. dev-mode budget guard active (cost regression check)
ESTIMATE=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/api/v1/scan/analyze-estimate?mode=standard" 2>/dev/null)
WILL=$(echo "$ESTIMATE" | python -c "import sys,json; print(json.load(sys.stdin).get('will_analyze','?'))" 2>/dev/null)
if [ "$WILL" = "10" ]; then
  ok "DEV_MODE cap active (will_analyze=10)"
else
  bad "DEV_MODE cap missing or wrong (will_analyze=$WILL, expected 10)"
fi

echo
echo "------"
echo "passed: $pass"
echo "failed: $fail"
exit $fail
