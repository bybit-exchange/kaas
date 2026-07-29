#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

PID_GO=""
PID_WEB=""

kill_tree() {
    local target_pid=$1
    local child_pids
    child_pids=$(pgrep -P "$target_pid" 2>/dev/null || true)
    for child in $child_pids; do
        kill_tree "$child"
    done
    kill "$target_pid" 2>/dev/null || true
}

cleanup() {
    echo ""
    echo "[dev] Shutting down all services..."
    for pid in $PID_GO $PID_WEB; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill_tree "$pid"
        fi
    done
    for pid in $PID_GO $PID_WEB; do
        if [ -n "$pid" ]; then
            wait "$pid" 2>/dev/null || true
        fi
    done
    echo "[dev] All services stopped."
}

# Ignore INT before spawning children — they inherit SIG_IGN so they won't
# be killed by the terminal's Ctrl+C directly. This eliminates the race
# condition where pnpm dies from SIGINT before cleanup can find its children.
trap '' INT

echo "[dev] Starting Go backend..."
(cd "$ROOT_DIR" && exec go run ./cmd/kaas -f etc/kaas-dev.toml) &
PID_GO=$!

echo "[dev] Starting Web dev server..."
(cd "$ROOT_DIR/web" && exec pnpm dev) &
PID_WEB=$!

# Now set the real trap — this shell handles INT via cleanup, while children
# still have SIG_IGN inherited and stay alive until we explicitly kill them.
trap cleanup EXIT INT TERM HUP

echo "[dev] All services starting. Press Ctrl+C to stop all."
echo ""

wait
