#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# 1. Stop the scheduler via PID file (never via process-name kill).
PID_FILE="data/run_scheduler.pid"
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping scheduler (PID $PID)..."
        kill -TERM "$PID"
        # Wait up to 30s for graceful shutdown.
        for i in $(seq 1 30); do
            kill -0 "$PID" 2>/dev/null || break
            sleep 1
        done
        if kill -0 "$PID" 2>/dev/null; then
            echo "Scheduler did not stop in 30s; aborting update."
            exit 1
        fi
        echo "Scheduler stopped."
    else
        echo "Stale PID file (process $PID not running); ignoring."
    fi
else
    echo "No scheduler PID file found; assuming not running."
fi

# 2. Refuse update if working tree has uncommitted edits to tracked files.
#    Never silently stash — that would mask intentional config edits.
if ! git diff --quiet HEAD; then
    echo "Refusing to update: uncommitted changes to tracked files."
    echo "Inspect with 'git status' and commit / stash manually first."
    exit 1
fi

# 3. Pull latest.
echo "Pulling latest code..."
git pull --rebase

# 4. Install dependencies (uses pyproject.toml from #107).
if [ -f .venv/bin/activate ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi
pip install -e .

# 5. Validate config (fail fast before any DB work).
python -c "from src.config_validator import validate_config; import config; validate_config(vars(config))"

# 6. Apply DB migrations (idempotent — safe on first run too).
python scripts/setup_db.py

# 7. Restart scheduler in the background.
nohup python scripts/run_scheduler.py > /dev/null 2>&1 &
echo "Update complete — scheduler restarted (PID $!)."
