#!/bin/bash
# Headless-Chrome screenshot of a running Zero Lab UI: tools/shoot.sh URL OUT.png [WIDTHxHEIGHT]
set -euo pipefail
size=${3:-1440x900}
prof=$(mktemp -d)
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu --hide-scrollbars --force-prefers-reduced-motion \
  --user-data-dir="$prof" --window-size="${size/x/,}" --timeout=6000 --screenshot="$2" "$1" 2>/dev/null
rm -rf "$prof"
