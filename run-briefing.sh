#!/bin/bash
#
# LaunchAgent wrapper for the daily markets briefing.
#
# Triggered by launchd on login (RunAtLoad) and periodically while the Mac is
# awake (StartInterval), so it fires shortly after you log in or unlock. The
# guards below make every trigger past the first one on a given weekday a no-op:
#
#   * weekday guard   -> skip Saturday and Sunday entirely
#   * once-per-day     -> skip if a successful run is already stamped for today
#   * lock            -> skip if another copy is mid-run (with stale-lock cleanup)
#
# A failed run is NOT stamped, so it retries on the next trigger.

set -u

# Resolve the project folder from this script's own location, so it works
# wherever the repo is cloned.
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="/opt/homebrew/bin/python3"
LOG="$PROJECT_DIR/logs/briefing.log"
STAMP="$PROJECT_DIR/logs/.last-run"
LOCK="$PROJECT_DIR/logs/.run.lock"
ENV_FILE="$PROJECT_DIR/.env"

export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "$PROJECT_DIR/logs"
cd "$PROJECT_DIR" || exit 1

today="$(date +%F)"          # 2026-09-03
dow="$(date +%u)"            # 1=Mon .. 7=Sun

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

# --- weekday guard -----------------------------------------------------------
if [ "$dow" -gt 5 ]; then
    exit 0
fi

# --- once-per-day guard ----------------------------------------------------
if [ -f "$STAMP" ] && [ "$(cat "$STAMP" 2>/dev/null)" = "$today" ]; then
    exit 0
fi

# --- lock (clear a stale one first) ---------------------------------------
if [ -d "$LOCK" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin +120 2>/dev/null)" ]; then
    rmdir "$LOCK" 2>/dev/null
fi
if ! mkdir "$LOCK" 2>/dev/null; then
    exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

# --- API keys (gitignored file, not the plist) --------------------------
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
else
    log "WARN $ENV_FILE not found; NYT_API_KEY / ANTHROPIC_API_KEY may be unset"
fi

# --- run ------------------------------------------------------------------
log "=== START ==="
"$PYTHON" briefing.py --summary --audio >> "$LOG" 2>&1
status=$?
log "=== EXIT $status ==="

if [ "$status" -eq 0 ]; then
    printf '%s\n' "$today" > "$STAMP"
else
    log "not stamping $today (exit $status); will retry on next trigger"
fi

exit "$status"
