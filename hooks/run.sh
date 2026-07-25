#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="python3"

event="${1:-}"
if [ "$event" = "SessionStart" ]
then
  exec "$PYTHON" "$DIR/session_start.py"
fi
if [ "$event" = "PreToolUse" ]
then
  exec "$PYTHON" "$DIR/pre_write.py"
fi
if [ "$event" = "PreCommit" ]
then
  exec "$PYTHON" "$DIR/pre_commit.py"
fi
if [ "$event" = "PostToolUse" ]
then
  exec "$PYTHON" "$DIR/record.py"
fi
if [ "$event" = "Stop" ]
then
  exit 0
fi
echo "usage: run.sh SessionStart|PreToolUse|PreCommit|PostToolUse|Stop" >&2
exit 2
