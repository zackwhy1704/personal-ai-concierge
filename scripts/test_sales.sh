#!/bin/bash
# ─────────────────────────────────────────────────
# Sales/Upsell E2E Test Script
# Tests all new sales endpoints: products, strategies, analytics, learning
# Usage: bash scripts/test_sales.sh https://your-backend.railway.app
# ─────────────────────────────────────────────────

API_URL="${1:?Usage: $0 <backend-url>}"
ADMIN_KEY="pac_admin_66a6c57cdd35f9aa1151da81f705c013"
PASS=0
FAIL=0

green() { echo -e "\033[32m✓ $1\033[0m"; PASS=$((PASS+1)); }
red() { echo -e "\033[31m✗ $1\033[0m"; FAIL=$((FAIL+1)); }

check_status() {
  local DESC="$1"
  local EXPECTED="$2"
  local ACTUAL="$3"
  if [ "$ACTUAL" = "$EXPECTED" ]; then
    green "$DESC"
  else
    red "$DESC (expected HTTP $EXPECTED, got $ACTUAL)"
  fi
}

echo "Sales/Upsell E2E Tests at: $API_URL"
echo "─────────────────────────────────────────"

# ============ SETUP: Create tenant with data ============
echo ""
echo "=== Setup: Create Test Tenant ==="
TENANT_RESPONSE=$(curl -s -X POST "$API_URL/api/tenants" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"Sales Test Hotel","slug":"sales-test-'$RANDOM'","plan":"professional","admin_phone_numbers":"+6500000000"}')

JWT_TOKEN=$(echo "$TENANT_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin).get('jwt_token',''))" 2>/dev/null)
TENANT_ID=$(echo "$TENANT_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin).get('tenant',{}).get('id',''))" 2>/dev/null)

if [ -n "$JWT_TOKEN" ] && [ "$JWT_TOKEN" != "" ]; then
  green "Test tenant created: $TENANT_ID"
else
  red "Tenant creation failed: $TENANT_RESPONSE"
  exit 1
fi

# Activate tenant
curl -s -X POST "$API_URL/api/tenants/me/activate" \
  -H "Authorization: Bearer $JWT_TOKEN" > /dev/null

# Upload knowledge for RAG pipeline tests
curl -s -X POST "$API_URL/api/knowledge" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Hotel Info","content":"Our hotel offers spa, dining, airport transfers, and room upgrades. Check-out is at 11 AM."}' > /dev/null

# Create guardrails
curl -s -X POST "$API_URL/api/guardrails/from-form" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tenant_name":"Sales Test Hotel","language":["en"],"persona":{"name":"SalesBot","tone":"friendly","greeting":"Welcome!"},"allowed_topics":["bookings","amenities","services"],"blocked_topics":[],"escalation_rules":[],"response_limits":{"max_response_length":500},"data_handling":{"collect_personal_data":false,"store_conversation_history":true,"retention_days":90},"custom_rules":[]}' > /dev/null

# ============ 1. PRODUCTS CRUD ============
echo ""
echo "=== Products: Create ==="

# Create product 1
P1_RESPONSE=$(curl -s -X POST "$API_URL/api/products" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name":"Spa Treatment",
    "description":"Relaxing full-body spa treatment with aromatherapy oils and hot stones",
    "category":"wellness",
    "price":150.00,
    "currency":"USD",
    "action_url":"https://hotel.com/book-spa",
    "tags":["spa","wellness","relaxation"]
  }')
P1_ID=$(echo "$P1_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
P1_STATUS=$(echo "$P1_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
if [ "$P1_STATUS" = "active" ]; then
  green "Product 1 created: $P1_ID (Spa Treatment)"
else
  red "Product 1 creation failed: $P1_RESPONSE"
fi

# Create product 2
P2_RESPONSE=$(curl -s -X POST "$API_URL/api/products" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name":"Airport Transfer",
    "description":"Luxury sedan airport pickup and dropoff service door-to-door",
    "category":"transport",
    "price":80.00,
    "currency":"USD",
    "action_url":"https://hotel.com/book-transfer",
    "tags":["airport","transport","luxury"]
  }')
P2_ID=$(echo "$P2_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
if [ -n "$P2_ID" ] && [ "$P2_ID" != "" ]; then
  green "Product 2 created: $P2_ID (Airport Transfer)"
else
  red "Product 2 creation failed: $P2_RESPONSE"
fi

# Create product 3
P3_RESPONSE=$(curl -s -X POST "$API_URL/api/products" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name":"Room Upgrade",
    "description":"Upgrade to a premium suite with ocean view and private balcony",
    "category":"rooms",
    "price":120.00,
    "currency":"USD",
    "tags":["upgrade","suite","premium"]
  }')
P3_ID=$(echo "$P3_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
if [ -n "$P3_ID" ] && [ "$P3_ID" != "" ]; then
  green "Product 3 created: $P3_ID (Room Upgrade)"
else
  red "Product 3 creation failed: $P3_RESPONSE"
fi

# List products
echo ""
echo "=== Products: List ==="
LIST_RESPONSE=$(curl -s "$API_URL/api/products" \
  -H "Authorization: Bearer $JWT_TOKEN")
PRODUCT_COUNT=$(echo "$LIST_RESPONSE" | python -c "import sys,json; print(len((lambda d: d if isinstance(d,list) else d.get('products',[]))(json.load(sys.stdin))))" 2>/dev/null)
if [ "$PRODUCT_COUNT" = "3" ]; then
  green "Listed 3 products"
else
  red "Expected 3 products, got $PRODUCT_COUNT"
fi

# Filter by category
LIST_FILTERED=$(curl -s "$API_URL/api/products?category=wellness" \
  -H "Authorization: Bearer $JWT_TOKEN")
FILTERED_COUNT=$(echo "$LIST_FILTERED" | python -c "import sys,json; print(len((lambda d: d if isinstance(d,list) else d.get('products',[]))(json.load(sys.stdin))))" 2>/dev/null)
if [ "$FILTERED_COUNT" = "1" ]; then
  green "Category filter works (wellness=1)"
else
  red "Category filter failed: expected 1, got $FILTERED_COUNT"
fi

# Get single product
echo ""
echo "=== Products: Get Single ==="
GET_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/products/$P1_ID" \
  -H "Authorization: Bearer $JWT_TOKEN")
check_status "Get product by ID" "200" "$GET_STATUS"

# Update product
echo ""
echo "=== Products: Update ==="
UPDATE_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X PATCH "$API_URL/api/products/$P1_ID" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"price":175.00,"description":"Premium full-body spa with aromatherapy and hot stones massage"}')
check_status "Update product price/description" "200" "$UPDATE_STATUS"

# Search products (semantic)
echo ""
echo "=== Products: Semantic Search ==="
SEARCH_RESPONSE=$(curl -s -X POST "$API_URL/api/products/search" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"I need to relax after a long flight"}')
SEARCH_COUNT=$(echo "$SEARCH_RESPONSE" | python -c "import sys,json; print(len(json.load(sys.stdin).get('results',[])))" 2>/dev/null)
if [ "$SEARCH_COUNT" -gt "0" ] 2>/dev/null; then
  SEARCH_TOP=$(echo "$SEARCH_RESPONSE" | python -c "import sys,json; r=json.load(sys.stdin)['results'][0]; print(f\"{r['name']} (score: {r['score']:.2f})\")" 2>/dev/null)
  green "Semantic search returned $SEARCH_COUNT results (top: $SEARCH_TOP)"
else
  red "Semantic search returned no results"
fi

# Bulk import
echo ""
echo "=== Products: Bulk Import ==="
IMPORT_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/products/import" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '[
    {"name":"Dinner Buffet","description":"International dinner buffet with live cooking stations","category":"dining","price":65.00,"currency":"USD"},
    {"name":"City Tour","description":"Half-day guided city tour visiting major landmarks","category":"activities","price":45.00,"currency":"USD"}
  ]')
check_status "Bulk import 2 products" "200" "$IMPORT_STATUS"

# Verify count after import
TOTAL_COUNT=$(curl -s "$API_URL/api/products" \
  -H "Authorization: Bearer $JWT_TOKEN" | python -c "import sys,json; print(len((lambda d: d if isinstance(d,list) else d.get('products',[]))(json.load(sys.stdin))))" 2>/dev/null)
if [ "$TOTAL_COUNT" = "5" ]; then
  green "Total products after import: 5"
else
  red "Expected 5 products total, got $TOTAL_COUNT"
fi

# ============ 2. UPSELL STRATEGIES ============
echo ""
echo "=== Upsell Strategies: Create ==="

# Strategy 1: Keyword-based
S1_RESPONSE=$(curl -s -X POST "$API_URL/api/upsell/strategies" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name":"Relaxation Upsell",
    "description":"Suggest spa when guest mentions stress or relaxation",
    "trigger_type":"keyword",
    "trigger_config":{"keywords":["tired","stressed","relax","spa","massage"]},
    "prompt_template":"Gently suggest our spa services as a way to unwind after their journey.",
    "priority":10,
    "is_active":true
  }')
S1_ID=$(echo "$S1_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
if [ -n "$S1_ID" ] && [ "$S1_ID" != "" ]; then
  green "Strategy 1 created: Keyword trigger (relaxation)"
else
  red "Strategy 1 creation failed: $S1_RESPONSE"
fi

# Strategy 2: Proactive
S2_RESPONSE=$(curl -s -X POST "$API_URL/api/upsell/strategies" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name":"Proactive Room Upgrade",
    "description":"Occasionally suggest room upgrades",
    "trigger_type":"proactive",
    "trigger_config":{"probability":0.5},
    "priority":5,
    "is_active":true
  }')
S2_ID=$(echo "$S2_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
if [ -n "$S2_ID" ] && [ "$S2_ID" != "" ]; then
  green "Strategy 2 created: Proactive trigger"
else
  red "Strategy 2 creation failed: $S2_RESPONSE"
fi

# List strategies
echo ""
echo "=== Upsell Strategies: List ==="
STRAT_LIST=$(curl -s "$API_URL/api/upsell/strategies" \
  -H "Authorization: Bearer $JWT_TOKEN")
STRAT_COUNT=$(echo "$STRAT_LIST" | python -c "import sys,json; print(len((lambda d: d if isinstance(d,list) else d.get('strategies',[]))(json.load(sys.stdin))))" 2>/dev/null)
if [ "$STRAT_COUNT" = "2" ]; then
  green "Listed 2 strategies"
else
  red "Expected 2 strategies, got $STRAT_COUNT"
fi

# Update strategy
echo ""
echo "=== Upsell Strategies: Update ==="
UPDATE_STRAT_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X PATCH "$API_URL/api/upsell/strategies/$S1_ID" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"priority":15}')
check_status "Update strategy priority" "200" "$UPDATE_STRAT_STATUS"

# Toggle strategy
echo ""
echo "=== Upsell Strategies: Toggle ==="
TOGGLE_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/upsell/strategies/$S2_ID/toggle" \
  -H "Authorization: Bearer $JWT_TOKEN")
check_status "Toggle strategy active status" "200" "$TOGGLE_STATUS"

# Re-toggle
TOGGLE2_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/upsell/strategies/$S2_ID/toggle" \
  -H "Authorization: Bearer $JWT_TOKEN")
check_status "Re-toggle strategy back" "200" "$TOGGLE2_STATUS"

# Test strategy matching
echo ""
echo "=== Upsell Strategies: Test Matching ==="
TEST_MATCH=$(curl -s -X POST "$API_URL/api/upsell/strategies/test" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Im feeling so tired and stressed after my flight"}')
MATCH_COUNT=$(echo "$TEST_MATCH" | python -c "import sys,json; print(len(json.load(sys.stdin).get('matched_strategies',[])))" 2>/dev/null)
if [ "$MATCH_COUNT" -gt "0" ] 2>/dev/null; then
  green "Strategy matching works ($MATCH_COUNT matched for 'tired and stressed')"
else
  red "No strategies matched 'tired and stressed' (expected keyword match)"
fi

# ============ 3. SALES ANALYTICS ============
echo ""
echo "=== Sales Analytics: Dashboard ==="
DASH_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/sales/dashboard" \
  -H "Authorization: Bearer $JWT_TOKEN")
check_status "Sales dashboard endpoint" "200" "$DASH_STATUS"

echo ""
echo "=== Sales Analytics: Conversion Funnel ==="
FUNNEL_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/sales/conversions" \
  -H "Authorization: Bearer $JWT_TOKEN")
check_status "Conversion funnel endpoint" "200" "$FUNNEL_STATUS"

echo ""
echo "=== Sales Analytics: Product Performance ==="
PROD_PERF_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/sales/products/performance" \
  -H "Authorization: Bearer $JWT_TOKEN")
check_status "Product performance endpoint" "200" "$PROD_PERF_STATUS"

echo ""
echo "=== Sales Analytics: Strategy Performance ==="
STRAT_PERF_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/sales/strategies/performance" \
  -H "Authorization: Bearer $JWT_TOKEN")
check_status "Strategy performance endpoint" "200" "$STRAT_PERF_STATUS"

echo ""
echo "=== Sales Analytics: Revenue ==="
REV_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/sales/revenue" \
  -H "Authorization: Bearer $JWT_TOKEN")
check_status "Revenue attribution endpoint" "200" "$REV_STATUS"

echo ""
echo "=== Sales Analytics: Cross-Sell Patterns ==="
CROSS_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/sales/cross-sell-patterns" \
  -H "Authorization: Bearer $JWT_TOKEN")
check_status "Cross-sell patterns endpoint" "200" "$CROSS_STATUS"

echo ""
echo "=== Sales Analytics: Attempts List ==="
ATTEMPTS_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/sales/attempts" \
  -H "Authorization: Bearer $JWT_TOKEN")
check_status "Upsell attempts list endpoint" "200" "$ATTEMPTS_STATUS"

# ============ 4. LEARNING ENDPOINTS ============
echo ""
echo "=== Learning: Analyze ==="
ANALYZE_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/sales/learning/analyze" \
  -H "Authorization: Bearer $JWT_TOKEN")
check_status "Learning analyze endpoint" "200" "$ANALYZE_STATUS"

echo ""
echo "=== Learning: Optimize ==="
OPTIMIZE_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/sales/learning/optimize" \
  -H "Authorization: Bearer $JWT_TOKEN")
check_status "Learning optimize endpoint" "200" "$OPTIMIZE_STATUS"

# ============ 5. RAG PIPELINE WITH SALES CONTEXT ============
echo ""
echo "=== RAG Pipeline: With Sales Context ==="
PIPELINE_RESPONSE=$(curl -s -X POST "$API_URL/api/webhooks/test-pipeline" \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"tenant_id\":\"$TENANT_ID\",\"message\":\"I am feeling stressed and need to relax\",\"session_id\":\"sales-test-session-$RANDOM\"}")
PIPELINE_STATUS=$(echo "$PIPELINE_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
PIPELINE_UPSELL=$(echo "$PIPELINE_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin).get('steps',{}).get('rag',{}).get('has_upsell',''))" 2>/dev/null)
if [ "$PIPELINE_STATUS" = "success" ]; then
  green "RAG pipeline with sales context works (upsell: $PIPELINE_UPSELL)"
  RESPONSE_PREVIEW=$(echo "$PIPELINE_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin).get('response','')[:120])" 2>/dev/null)
  echo "  Response: $RESPONSE_PREVIEW..."
else
  red "RAG pipeline failed: $PIPELINE_RESPONSE"
fi

# Test pipeline without upsell trigger
PIPELINE2_RESPONSE=$(curl -s -X POST "$API_URL/api/webhooks/test-pipeline" \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"tenant_id\":\"$TENANT_ID\",\"message\":\"What is the checkout time?\",\"session_id\":\"sales-test-session2-$RANDOM\"}")
PIPELINE2_STATUS=$(echo "$PIPELINE2_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
if [ "$PIPELINE2_STATUS" = "success" ]; then
  green "RAG pipeline works for regular queries too"
else
  red "RAG pipeline failed for regular query: $PIPELINE2_RESPONSE"
fi

# ============ 6. PRODUCT DELETE ============
echo ""
echo "=== Products: Delete ==="
DEL_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "$API_URL/api/products/$P3_ID" \
  -H "Authorization: Bearer $JWT_TOKEN")
check_status "Delete product" "200" "$DEL_STATUS"

# Verify 404 after delete
GET_DELETED=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/products/$P3_ID" \
  -H "Authorization: Bearer $JWT_TOKEN")
check_status "Deleted product returns 404" "404" "$GET_DELETED"

# ============ 7. STRATEGY DELETE ============
echo ""
echo "=== Upsell Strategies: Delete ==="
DEL_STRAT_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "$API_URL/api/upsell/strategies/$S1_ID" \
  -H "Authorization: Bearer $JWT_TOKEN")
check_status "Delete strategy" "200" "$DEL_STRAT_STATUS"

# ============ 8. ERROR CASES ============
echo ""
echo "=== Error Cases ==="

# Invalid product ID
ERR1_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/products/invalid-uuid" \
  -H "Authorization: Bearer $JWT_TOKEN")
if [ "$ERR1_STATUS" = "404" ] || [ "$ERR1_STATUS" = "422" ]; then
  green "Invalid product ID returns error ($ERR1_STATUS)"
else
  red "Invalid product ID: expected 404/422, got $ERR1_STATUS"
fi

# Create product without name
ERR2_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/products" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"description":"No name product"}')
check_status "Product without name returns 422" "422" "$ERR2_STATUS"

# Unauthenticated request
ERR3_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/products")
if [ "$ERR3_STATUS" = "401" ] || [ "$ERR3_STATUS" = "403" ]; then
  green "Unauthenticated products request rejected ($ERR3_STATUS)"
else
  red "Unauthenticated request: expected 401/403, got $ERR3_STATUS"
fi

# Admin-only learning/run endpoint with tenant JWT
ERR4_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/sales/learning/run" \
  -H "Authorization: Bearer $JWT_TOKEN")
if [ "$ERR4_STATUS" = "403" ]; then
  green "Admin-only endpoint rejected tenant JWT"
else
  red "Admin-only endpoint: expected 403, got $ERR4_STATUS"
fi

# Summary
echo ""
echo "═════════════════════════════════════════"
echo "Sales E2E Results: $PASS passed, $FAIL failed"
echo "═════════════════════════════════════════"

if [ "$FAIL" -eq 0 ]; then
  echo -e "\033[32mAll sales tests passed!\033[0m"
else
  echo -e "\033[31mSome tests failed. Check the output above.\033[0m"
fi
