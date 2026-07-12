#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

skills_root() {
  if [ -n "${ADW_SKILLS_ROOT:-}" ]; then
    printf '%s\n' "$ADW_SKILLS_ROOT"
    return
  fi
  cd "$DIR/../.." && pwd
}

select_python() {
  if [ -n "${SML_PYTHON:-}" ] && [ -x "$SML_PYTHON" ]; then
    printf '%s\n' "$SML_PYTHON"
    return
  fi

  root="$(skills_root)"
  for candidate in \
    "$root/skill-model-loader/.venv/bin/python" \
    "$root/clean-coder-discipline/hooks/.venv/bin/python" \
    "$root/clean-coder-discipline/.venv/bin/python" \
    "${CLEANCODER_HOME:-${HOME:-}/.clean-coder-discipline}/.venv/bin/python"
  do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return
    fi
  done

  printf '%s\n' python3
}

PYTHON="$(select_python)"

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
  exec "$PYTHON" "$DIR/gate.py"
fi
echo "usage: run.sh SessionStart|PreToolUse|PreCommit|PostToolUse|Stop" >&2
exit 2
