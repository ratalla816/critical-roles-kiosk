#!/bin/bash
# MCI5 Critical Roles Kiosk — startup script
# Called by ~/.bashrc on every DevSpace terminal start

APP_DIR="$HOME/critical-roles-kiosk"
LOG_FILE="$APP_DIR/kiosk.log"
PID_FILE="$APP_DIR/kiosk.pid"

# Check if already running
if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    echo "[kiosk] Already running (PID $PID)"
    exit 0
  fi
fi

cd "$APP_DIR" || exit 1

# Activate venv if present
if [ -f "$APP_DIR/venv/bin/activate" ]; then
  source "$APP_DIR/venv/bin/activate"
fi

echo "[kiosk] Starting MCI5 Critical Roles Kiosk..."
nohup python3 app.py >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
echo "[kiosk] Started (PID $(cat $PID_FILE)) — http://localhost:5001"
