#!/usr/bin/env bash
# ship.sh — Build-session close-out helper for ComplyOS.
# Runs lint → type-check → tests → shows git status → prompts for commit.
# Usage: ./scripts/ship.sh ["optional commit message"]

set -euo pipefail

cd "$(dirname "$0")/.."

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

fail=0

echo ""
echo "========================================"
echo "   ComplyOS Ship Check"
echo "========================================"
echo ""

# 1. Lint
echo -n "▶ ruff check … "
if uv run --extra dev ruff check complyos tests >/dev/null 2>&1; then
    echo -e "${GREEN}✓ clean${NC}"
else
    echo -e "${RED}✗ failed${NC}"
    fail=1
fi

# 2. Type check
echo -n "▶ mypy … "
if uv run --extra dev mypy complyos --ignore-missing-imports >/dev/null 2>&1; then
    echo -e "${GREEN}✓ clean${NC}"
else
    echo -e "${RED}✗ failed${NC}"
    fail=1
fi

# 3. Tests
echo -n "▶ pytest … "
if uv run --extra dev pytest -q --tb=short >/dev/null 2>&1; then
    echo -e "${GREEN}✓ passed${NC}"
else
    echo -e "${RED}✗ failed${NC}"
    fail=1
fi

echo ""
echo "========================================"

if [ "$fail" -eq 1 ]; then
    echo -e "${RED}Ship blocked — fix failures above before committing.${NC}"
    exit 1
fi

# 4. Git status
echo ""
echo "Git status:"
git status --short

count=$(git status --short | wc -l | tr -d ' ')
if [ "$count" -eq 0 ]; then
    echo -e "${GREEN}Working tree clean. Nothing to ship.${NC}"
    exit 0
fi

echo ""
echo "$count file(s) changed."
echo ""

# 5. Commit
msg="${1:-}"
if [ -z "$msg" ]; then
    echo -n "Commit message (or 'n' to skip): "
    read -r msg
fi

if [ "$msg" = "n" ] || [ "$msg" = "N" ]; then
    echo -e "${YELLOW}Skipped commit. Run again when ready.${NC}"
    exit 0
fi

git add -A
git commit -m "$msg"
echo -e "${GREEN}✓ Committed.${NC}"
echo ""
echo "Push when ready: git push -u origin main"
