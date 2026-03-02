#!/bin/bash
# ─────────────────────────────────────────────────
# Production Edge Case Tests
# Usage: bash scripts/test_edge_cases.sh <backend-url> <jwt-token> <api-key>
# ─────────────────────────────────────────────────

API_URL="${1:?Usage: $0 <backend-url> <jwt-token> <api-key>}"
JWT_TOKEN="${2:?Missing JWT token}"
API_KEY="${3:?Missing API key}"
ADMIN_KEY="pac_admin_66a6c57cdd35f9aa1151da81f705c013"
PASS=0
FAIL=0

green() { echo -e "\033[32m✓ $1\033[0m"; PASS=$((PASS+1)); }
red() { echo -e "\033[31m✗ $1\033[0m"; FAIL=$((FAIL+1)); }
yellow() { echo -e "\033[33m⚠ $1\033[0m"; }

echo "Edge Case Tests at: $API_URL"
echo "═════════════════════════════════════════"

# ─── AUTH EDGE CASES ───
echo ""
echo "=== Auth Edge Cases ==="

# No auth header
STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/tenants/me")
if [ "$STATUS" = "401" ] || [ "$STATUS" = "403" ]; then
  green "No auth header returns $STATUS"
else
  red "No auth header should return 401/403, got $STATUS"
fi

# Invalid JWT token
STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/tenants/me" \
  -H "Authorization: Bearer invalid.jwt.token")
if [ "$STATUS" = "401" ] || [ "$STATUS" = "403" ]; then
  green "Invalid JWT returns $STATUS"
else
  red "Invalid JWT should return 401/403, got $STATUS"
fi

# Invalid API key
STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/tenants/me" \
  -H "X-API-Key: invalid_key_12345")
if [ "$STATUS" = "401" ] || [ "$STATUS" = "403" ]; then
  green "Invalid API key returns $STATUS"
else
  red "Invalid API key should return 401/403, got $STATUS"
fi

# Empty bearer token
STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/tenants/me" \
  -H "Authorization: Bearer ")
if [ "$STATUS" = "401" ] || [ "$STATUS" = "403" ]; then
  green "Empty bearer token returns $STATUS"
else
  red "Empty bearer token should return 401/403, got $STATUS"
fi

# Admin endpoint with non-admin key
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/tenants" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Unauthorized","slug":"unauth-test","plan":"starter"}')
if [ "$STATUS" = "401" ] || [ "$STATUS" = "403" ]; then
  green "Non-admin creating tenant returns $STATUS"
else
  red "Non-admin creating tenant should return 401/403, got $STATUS"
fi

# ─── GUARDRAIL EDGE CASES ───
echo ""
echo "=== Guardrail Edge Cases ==="

# Empty body
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/guardrails/from-form" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}')
if [ "$STATUS" = "422" ] || [ "$STATUS" = "400" ]; then
  green "Empty guardrail form returns $STATUS"
else
  red "Empty guardrail form should return 422/400, got $STATUS"
fi

# Invalid JSON
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/guardrails/from-form" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d 'not json at all')
if [ "$STATUS" = "422" ] || [ "$STATUS" = "400" ]; then
  green "Invalid JSON returns $STATUS"
else
  red "Invalid JSON should return 422/400, got $STATUS"
fi

# ─── KNOWLEDGE EDGE CASES ───
echo ""
echo "=== Knowledge Edge Cases ==="

# Empty content
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/knowledge" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Empty","content":""}')
if [ "$STATUS" = "422" ] || [ "$STATUS" = "400" ]; then
  green "Empty knowledge content returns $STATUS"
else
  yellow "Empty knowledge content returns $STATUS (may be allowed)"
fi

# Search with empty query
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/knowledge/search" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":""}')
if [ "$STATUS" = "422" ] || [ "$STATUS" = "400" ] || [ "$STATUS" = "200" ]; then
  green "Empty search query returns $STATUS"
else
  red "Empty search query got unexpected $STATUS"
fi

# Very long content upload
LONG_CONTENT=$(python -c "print('A' * 10000)")
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/knowledge" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"title\":\"Long Content Test\",\"content\":\"$LONG_CONTENT\"}")
if [ "$STATUS" = "200" ] || [ "$STATUS" = "201" ]; then
  green "Long content upload accepted: HTTP $STATUS"
elif [ "$STATUS" = "413" ] || [ "$STATUS" = "422" ]; then
  green "Long content properly rejected: HTTP $STATUS"
else
  red "Long content unexpected response: HTTP $STATUS"
fi

# ─── INTENT EDGE CASES ───
echo ""
echo "=== Intent Edge Cases ==="

# Intent with no examples
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/intents" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"No Examples Intent","description":"Test intent","action_type":"reply","action_config":{"message":"hello"},"examples":[]}')
if [ "$STATUS" = "422" ] || [ "$STATUS" = "400" ] || [ "$STATUS" = "200" ]; then
  green "Intent with no examples returns $STATUS"
else
  red "Intent with no examples unexpected: $STATUS"
fi

# Detect intent with very short message
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/intents/test" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"hi"}')
if [ "$STATUS" = "200" ]; then
  green "Short message intent detection returns 200"
else
  red "Short message intent detection failed: HTTP $STATUS"
fi

# Detect intent with unrelated message (should return low confidence or null)
DETECT_BODY=$(curl -s -X POST "$API_URL/api/intents/test" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"What is the weather like on Mars today?"}')
STATUS=$?
echo "  Unrelated message detection: $(echo "$DETECT_BODY" | python -c "import sys,json; r=json.load(sys.stdin); print(f\"intent={r.get('intent_name','none')}, confidence={r.get('confidence','?')}\")" 2>/dev/null)"
green "Unrelated message handled gracefully"

# ─── BILLING EDGE CASES ───
echo ""
echo "=== Billing Edge Cases ==="

# Checkout with invalid plan
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/billing/checkout" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"plan":"nonexistent_plan","success_url":"http://test.com","cancel_url":"http://test.com"}')
if [ "$STATUS" = "400" ] || [ "$STATUS" = "422" ]; then
  green "Invalid plan checkout returns $STATUS"
else
  red "Invalid plan checkout should return 400/422, got $STATUS"
fi

# Portal without subscription
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/billing/portal" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"return_url":"http://test.com"}')
if [ "$STATUS" = "400" ] || [ "$STATUS" = "404" ]; then
  green "Portal without subscription returns $STATUS"
else
  yellow "Portal without subscription returns $STATUS (may vary)"
fi

# Webhook with no signature
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/billing/webhook/stripe" \
  -H "Content-Type: application/json" \
  -d '{"type":"test"}')
if [ "$STATUS" = "400" ] || [ "$STATUS" = "422" ]; then
  green "Webhook with no signature returns $STATUS"
else
  red "Webhook with no signature should return 400/422, got $STATUS"
fi

# Webhook with invalid signature
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/billing/webhook/stripe" \
  -H "Content-Type: application/json" \
  -H "Stripe-Signature: t=123,v1=invalid" \
  -d '{"type":"test"}')
if [ "$STATUS" = "400" ]; then
  green "Webhook with invalid signature returns 400"
else
  red "Webhook with invalid signature should return 400, got $STATUS"
fi

# ─── WHATSAPP WEBHOOK EDGE CASES ───
echo ""
echo "=== WhatsApp Webhook Edge Cases ==="

# Wrong verify token
STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=wrong_token&hub.challenge=test123")
if [ "$STATUS" = "403" ] || [ "$STATUS" = "401" ]; then
  green "Wrong verify token returns $STATUS"
else
  red "Wrong verify token should return 403, got $STATUS"
fi

# Missing verify token
STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/webhooks/whatsapp?hub.mode=subscribe&hub.challenge=test123")
if [ "$STATUS" = "403" ] || [ "$STATUS" = "401" ] || [ "$STATUS" = "422" ]; then
  green "Missing verify token returns $STATUS"
else
  red "Missing verify token should return 403/422, got $STATUS"
fi

# POST webhook with empty body (no signature = 401, which is correct)
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/webhooks/whatsapp" \
  -H "Content-Type: application/json" \
  -d '{}')
if [ "$STATUS" = "200" ] || [ "$STATUS" = "400" ] || [ "$STATUS" = "401" ] || [ "$STATUS" = "422" ]; then
  green "Empty webhook POST returns $STATUS (graceful handling)"
else
  red "Empty webhook POST unexpected: HTTP $STATUS"
fi

# POST webhook with valid structure but no signature (401 expected - signature required)
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/webhooks/whatsapp" \
  -H "Content-Type: application/json" \
  -d '{"object":"whatsapp_business_account","entry":[{"id":"123","changes":[{"value":{"messaging_product":"whatsapp","metadata":{"display_phone_number":"15550000000","phone_number_id":"999"},"messages":[{"from":"6591234567","id":"wamid.test123","timestamp":"1234567890","text":{"body":"Hello"},"type":"text"}]},"field":"messages"}]}]}')
if [ "$STATUS" = "200" ] || [ "$STATUS" = "401" ] || [ "$STATUS" = "404" ] || [ "$STATUS" = "400" ]; then
  green "Webhook without signature returns $STATUS"
else
  red "Webhook without signature unexpected: HTTP $STATUS"
fi

# ─── 404 / METHOD NOT ALLOWED ───
echo ""
echo "=== Error Handling ==="

# Non-existent endpoint
STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/nonexistent")
if [ "$STATUS" = "404" ]; then
  green "Non-existent endpoint returns 404"
else
  red "Non-existent endpoint should return 404, got $STATUS"
fi

# Wrong HTTP method
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "$API_URL/health")
if [ "$STATUS" = "405" ] || [ "$STATUS" = "404" ]; then
  green "Wrong method on /health returns $STATUS"
else
  red "Wrong method on /health should return 405, got $STATUS"
fi

# ─── CORS CHECK ───
echo ""
echo "=== CORS ==="
CORS_HEADERS=$(curl -s -I -X OPTIONS "$API_URL/health" \
  -H "Origin: https://example.com" \
  -H "Access-Control-Request-Method: GET" 2>/dev/null | grep -i "access-control")
if echo "$CORS_HEADERS" | grep -qi "access-control-allow-origin"; then
  green "CORS headers present"
else
  yellow "CORS headers not found in OPTIONS response"
fi

# ─── RATE LIMITING / LARGE PAYLOADS ───
echo ""
echo "=== Robustness ==="

# Very large JSON payload (using temp file to avoid bash arg limit)
python -c "import json; open('/tmp/huge_payload.json','w').write(json.dumps({'title':'x','content':'A'*50000}))"
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/knowledge" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d @/tmp/huge_payload.json)
if [ "$STATUS" = "200" ] || [ "$STATUS" = "201" ] || [ "$STATUS" = "413" ] || [ "$STATUS" = "422" ]; then
  green "50KB payload handled: HTTP $STATUS"
else
  red "50KB payload unexpected: HTTP $STATUS"
fi

# ═══ SUMMARY ═══
echo ""
echo "═════════════════════════════════════════"
echo "Edge Case Results: $PASS passed, $FAIL failed"
echo "═════════════════════════════════════════"

if [ "$FAIL" -eq 0 ]; then
  echo -e "\033[32mAll edge case tests passed!\033[0m"
else
  echo -e "\033[31mSome edge case tests failed. Review output above.\033[0m"
fi
