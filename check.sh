#!/bin/bash
# Engineering Director Dashboard — Health Check
# Run this after cloning to verify everything is set up correctly.
set -e
cd "$(dirname "$0")"

passed=0
failed=0

check() {
  local label="$1"
  shift
  if "$@" > /dev/null 2>&1; then
    echo "  [OK] $label"
    passed=$((passed + 1))
  else
    echo "  [FAIL] $label"
    failed=$((failed + 1))
  fi
}

echo "=== eng-dashboard health check ==="
echo ""

echo "1. Prerequisites"
check "Python 3.11+ installed" python3 --version
check "uv installed" command -v uv
check "Node.js 18+ installed" node --version
check "npm installed" command -v npm

echo ""
echo "2. Dependencies"
check "Python deps synced" uv sync --frozen
if [ -d "frontend/node_modules" ]; then
  check "Frontend deps installed" test -d frontend/node_modules
else
  echo "  [SKIP] Frontend deps not installed (run: cd frontend && npm ci)"
fi

echo ""
echo "3. Backend"
check "Backend imports cleanly" python -c "from backend.main import app"
check "Snyk service available" python -c "from backend.services.snyk_service import get_snyk_service"
check "Git provider factory available" python -c "from backend.services.git_providers.factory import create_provider"
check "Issue tracker factory available" python -c "from backend.issue_tracker.factory import create_issue_tracker"

echo ""
echo "4. Tests"
check "Backend tests pass" python -m pytest backend/tests/ -q --tb=line

echo ""
echo "5. Frontend"
if [ -d "frontend/node_modules" ]; then
  check "TypeScript compiles" bash -c "cd frontend && npx tsc --noEmit"
else
  echo "  [SKIP] Frontend not installed"
fi

echo ""
echo "6. Configuration"
if [ -f ".env" ]; then
  check ".env exists" test -f .env
else
  echo "  [WARN] No .env file (copy .env.example to .env)"
fi
if [ -f "config/organization.yaml" ] || ls config/domains/*.yaml > /dev/null 2>&1; then
  check "Organization config exists" true
else
  echo "  [WARN] No organization config (copy config/organization.example.yaml)"
fi

echo ""
echo "=== Results: $passed passed, $failed failed ==="
if [ "$failed" -gt 0 ]; then
  exit 1
fi
echo "All checks passed. Run ./start.sh to launch the dashboard."
