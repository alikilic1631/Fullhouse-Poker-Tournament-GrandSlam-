#!/usr/bin/env bash
# Build submission_v15.zip with bot.py + data/ at root (no extra files).
# Run from project root.
set -euo pipefail

cd "$(dirname "$0")/submission"

# Clean any leftover artifacts
rm -f submission_v15.zip
rm -rf __pycache__ data/__pycache__

# Verify required files exist
[ -f bot.py ] || { echo "ERROR: submission/bot.py missing"; exit 1; }
[ -d data ] || { echo "ERROR: submission/data/ missing"; exit 1; }
[ -f data/equity_tables.npz ] || { echo "ERROR: data/equity_tables.npz missing"; exit 1; }

# Build the zip with bot.py at root + data/ at root
zip -r submission_v15.zip bot.py data/equity_tables.npz

echo ""
echo "=== zip structure ==="
unzip -l submission_v15.zip

echo ""
echo "=== integrity ==="
ls -la submission_v15.zip
shasum -a 256 submission_v15.zip
