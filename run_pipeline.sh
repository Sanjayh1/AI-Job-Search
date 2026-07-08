#!/bin/bash
# Full job hunting pipeline:
# 1. Tell Claude Code to search + score jobs (Claude handles this via MCP + browser)
# 2. Auto-apply to all Priority jobs found
# Run this by telling Claude: "run my job pipeline"
# Or run the apply step alone:
#   python3 apply.py --all-priority

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="/usr/bin/python3"

echo "================================"
echo " Job Hunter — Apply Pipeline"
echo " $(date)"
echo "================================"

echo ""
echo "Applying to all Priority jobs in tracker..."
"$PYTHON" "$SCRIPT_DIR/apply.py" --all-priority

echo ""
echo "Done. Check tracker.csv and screenshots/ for results."
