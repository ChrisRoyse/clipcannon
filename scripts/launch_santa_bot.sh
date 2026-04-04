#!/bin/bash
# Launch Santa clone bot into Google Meet
# Run: bash scripts/launch_santa_bot.sh [meet_url]
set -e

MEET_URL="${1:-https://meet.google.com/ecu-zoxq-ptq}"
LOG="/tmp/santa_bot.log"

echo "Killing existing browsers..."
pkill -f "chromium.*meet.google" 2>/dev/null || true
sleep 1

echo "Starting Santa bot..."
echo "Meet URL: $MEET_URL"
echo "Log: $LOG"
echo ""

cd /home/cabdru/clipcannon
python scripts/santa_meet_bot.py "$MEET_URL" > "$LOG" 2>&1 &
PID=$!
echo "PID: $PID"

sleep 12
echo ""
echo "=== Bot Output ==="
cat "$LOG"
echo ""
echo "=== Status ==="
if kill -0 $PID 2>/dev/null; then
    echo "Bot is RUNNING (PID $PID)"
else
    echo "Bot EXITED"
fi
