#!/bin/bash
# Double-click in Finder. Voice starts automatically; --no-voice opts out.
set -uo pipefail
JARVIS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! "$JARVIS_DIR/jarvis" "$@"; then
    printf '\nJarvis could not start. Check the error above.\n'
    printf 'Press Return to close this window.'
    read -r _
    exit 1
fi
