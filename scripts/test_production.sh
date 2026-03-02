#!/bin/bash
# ─────────────────────────────────────────────────
# Production E2E Test Script
# Usage: bash scripts/test_production.sh https://your-backend.railway.app
# ─────────────────────────────────────────────────

set -e

API_URL="${1:?Usage: $0 <backend-url>}"
ADMIN_KEY="pac_admin_66a6c57cdd35f9aa1151da81f705c013"
PASS=0
FAIL=0

green() { echo -e "\033[32m✓ $1\033[0m"; PASS=$((PASS+1)); }
red() { echo -e "\033[31m✗ $1\033[0m"; FAIL=$((FAIL+1)); }

echo "Testing production API at: $API_URL"
echo "─────────────────────────────────────────"

# 1. Health check
echo ""
echo "=== Health Check ==="
STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/health")
if [ "$STATUS" = "200" ]; then
  BODY=$(curl -s "$API_URL/health")
  green "Health check OK: $BODY"
else
  red "Health check failed: HTTP $STATUS"
fi

# 2. Create tenant
echo ""
echo "=== Create Test Tenant ==="
TENANT_RESPONSE=$(curl -s -X POST "$API_URL/api/tenants" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"E2E Test Hotel","slug":"e2e-test-'$RANDOM'","plan":"professional","admin_phone_numbers":"+6500000000"}')

API_KEY=$(echo "$TENANT_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin).get('api_key',''))" 2>/dev/null)
JWT_TOKEN=$(echo "$TENANT_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin).get('jwt_token',''))" 2>/dev/null)
TENANT_ID=$(echo "$TENANT_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin).get('tenant',{}).get('id',''))" 2>/dev/null)

if [ -n "$API_KEY" ] && [ "$API_KEY" != "" ]; then
  green "Tenant created: $TENANT_ID"
  echo "  API Key: ${API_KEY:0:20}..."
  echo "  JWT: ${JWT_TOKEN:0:30}..."
else
  red "Tenant creation failed: $TENANT_RESPONSE"
  exit 1
fi

# 3. Get tenant info via JWT
echo ""
echo "=== Auth: JWT Token ==="
ME_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/tenants/me" \
  -H "Authorization: Bearer $JWT_TOKEN")
if [ "$ME_STATUS" = "200" ]; then
  green "JWT auth works"
else
  red "JWT auth failed: HTTP $ME_STATUS"
fi

# 4. Get tenant info via API key
echo ""
echo "=== Auth: API Key ==="
ME_STATUS2=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/tenants/me" \
  -H "X-API-Key: $API_KEY")
if [ "$ME_STATUS2" = "200" ]; then
  green "API key auth works"
else
  red "API key auth failed: HTTP $ME_STATUS2"
fi

# 5. Create guardrail
echo ""
echo "=== Guardrails ==="
GR_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/guardrails/from-form" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_name\":\"E2E Test Hotel\",
    \"language\":[\"en\"],
    \"persona\":{\"name\":\"TestBot\",\"tone\":\"friendly\",\"greeting\":\"Hello! How can I help?\"},
    \"allowed_topics\":[\"bookings\",\"amenities\"],
    \"blocked_topics\":[\"politics\"],
    \"escalation_rules\":[{\"trigger\":\"speak to manager\",\"action\":\"escalate\"}],
    \"response_limits\":{\"max_response_length\":500,\"max_conversation_turns\":50,\"session_timeout_minutes\":30},
    \"data_handling\":{\"collect_personal_data\":false,\"store_conversation_history\":true,\"retention_days\":90},
    \"custom_rules\":[]
  }")
if [ "$GR_STATUS" = "200" ]; then
  green "Guardrail created from form"
else
  red "Guardrail creation failed: HTTP $GR_STATUS"
fi

# Verify active guardrail
GR_ACTIVE=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/guardrails/active" \
  -H "Authorization: Bearer $JWT_TOKEN")
if [ "$GR_ACTIVE" = "200" ]; then
  green "Active guardrail retrieved"
else
  red "Active guardrail not found: HTTP $GR_ACTIVE"
fi

# 6. Upload knowledge
echo ""
echo "=== Knowledge Base ==="
KB_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/knowledge" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title":"Hotel Information",
    "content":"E2E Test Hotel is a luxury 5-star hotel located in Singapore. We offer deluxe rooms starting at $200 per night. Check-in time is 3 PM and check-out is 11 AM. We have a rooftop pool, spa, gym, and three restaurants. Free WiFi is available throughout the property. Airport shuttle service costs $30 per trip."
  }')
if [ "$KB_STATUS" = "200" ]; then
  green "Knowledge document uploaded and embedded"
else
  red "Knowledge upload failed: HTTP $KB_STATUS"
fi

# Search knowledge
echo ""
SEARCH_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/knowledge/search" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"What time is check in?"}')
if [ "$SEARCH_STATUS" = "200" ]; then
  SEARCH_RESULT=$(curl -s -X POST "$API_URL/api/knowledge/search" \
    -H "Authorization: Bearer $JWT_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"query":"What time is check in?"}')
  green "Knowledge search works"
  echo "  Result preview: $(echo "$SEARCH_RESULT" | python -c "import sys,json; r=json.load(sys.stdin); print(r[0].get('content','')[:80] + '...' if r else 'empty')" 2>/dev/null)"
else
  red "Knowledge search failed: HTTP $SEARCH_STATUS"
fi

# 7. Create intent
echo ""
echo "=== Intents ==="
INTENT_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/intents" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name":"Room Booking",
    "description":"Guest wants to book a room",
    "action_type":"link",
    "action_config":{"url":"https://hotel.com/book"},
    "examples":["I want to book a room","reserve accommodation","make a reservation"]
  }')
if [ "$INTENT_STATUS" = "200" ]; then
  green "Intent created with vector embeddings"
else
  red "Intent creation failed: HTTP $INTENT_STATUS"
fi

# Test intent detection
DETECT_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/intents/test" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"I would like to book a room for next weekend"}')
if [ "$DETECT_STATUS" = "200" ]; then
  DETECT_RESULT=$(curl -s -X POST "$API_URL/api/intents/test" \
    -H "Authorization: Bearer $JWT_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"message":"I would like to book a room for next weekend"}')
  green "Intent detection works"
  echo "  Detected: $(echo "$DETECT_RESULT" | python -c "import sys,json; r=json.load(sys.stdin); print(f\"{r.get('intent_name','?')} (confidence: {r.get('confidence','?')})\")" 2>/dev/null)"
else
  red "Intent detection failed: HTTP $DETECT_STATUS"
fi

# 8. Billing endpoints
echo ""
echo "=== Billing ==="
SUB_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/billing/subscription" \
  -H "Authorization: Bearer $JWT_TOKEN")
if [ "$SUB_STATUS" = "200" ]; then
  green "Subscription status endpoint works"
else
  red "Subscription status failed: HTTP $SUB_STATUS"
fi

# 9. Usage endpoints
echo ""
echo "=== Usage ==="
USAGE_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/usage/monthly" \
  -H "Authorization: Bearer $JWT_TOKEN")
if [ "$USAGE_STATUS" = "200" ]; then
  green "Monthly usage endpoint works"
else
  red "Monthly usage failed: HTTP $USAGE_STATUS"
fi

# 10. WhatsApp webhook verification
echo ""
echo "=== WhatsApp Webhook ==="
WH_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=pac_verify_2026_concierge&hub.challenge=12345")
if [ "$WH_STATUS" = "200" ]; then
  green "WhatsApp webhook verification works"
else
  red "WhatsApp webhook verification failed: HTTP $WH_STATUS"
fi

# Summary
echo ""
echo "═════════════════════════════════════════"
echo "Results: $PASS passed, $FAIL failed"
echo "═════════════════════════════════════════"

if [ "$FAIL" -eq 0 ]; then
  echo -e "\033[32mAll tests passed! Production is ready.\033[0m"
else
  echo -e "\033[31mSome tests failed. Check the output above.\033[0m"
fi

echo ""
echo "Tenant credentials for dashboard login:"
echo "  JWT Token: $JWT_TOKEN"
echo "  API Key: $API_KEY"
echo "  Tenant ID: $TENANT_ID"
