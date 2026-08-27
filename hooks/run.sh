#!/bin/sh
set -eu

# CDPATH is unset first because an exported CDPATH makes cd echo the directory it landed in, which
# would end up glued into these paths.
unset CDPATH
DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION_FILE="$(cd "$DIR/.." && pwd)/.python-version"
FLOOR=""

DISPATCH="SessionStart:session_start.py UserPromptSubmit:prompt_submit.py PreToolUse:pre_tool.py PreCommit:pre_tool.py PostToolUse:record.py PostToolBatch:batch.py PostToolUseFailure:failure.py SubagentStart:subagent_start.py SubagentStop:subagent_stop.py Stop:stop.py JudgeReview:judge_review.py"

PROBE='import sys
floor = tuple(int(part) for part in sys.argv[1].split("."))
sys.exit(0 if sys.version_info[:len(floor)] >= floor else 1)'

die() {
  echo "run.sh: $1" >&2
  exit 2
}

meets_floor() {
  [ -x "$1" ] && "$1" -c "$PROBE" "$FLOOR" >/dev/null 2>&1
}

# Every candidate is probed instead of trusted by name, because a python3 on PATH is routinely an
# older system build that cannot import this codebase.
resolve_python() {
  if [ -n "${ADW_PYTHON:-}" ]
  then
    override="$(command -v "$ADW_PYTHON" 2>/dev/null || true)"
    if meets_floor "$override"
    then
      printf '%s\n' "$override"
    fi
    return 0
  fi
  IFS=:
  set -- $PATH
  unset IFS
  for dir in "$@"
  do
    [ -n "$dir" ] || dir="."
    # Two-digit names come first so a modern build outranks a single-digit minor beside it.
    for candidate in "$dir"/python3.[0-9][0-9] "$dir"/python3.[0-9] "$dir"/python3 "$dir"/python
    do
      if meets_floor "$candidate"
      then
        printf '%s\n' "$candidate"
        return 0
      fi
    done
  done
  return 0
}

event="${1:-}"
usage="usage: run.sh "
sep=""
for pair in $DISPATCH
do
  name=${pair%%:*}
  usage="$usage$sep$name"
  sep="|"
  if [ "$event" = "$name" ]
  then
    script=${pair#*:}
    [ -f "$DIR/$script" ] || die "misconfigured install: missing $DIR/$script"
    [ -f "$VERSION_FILE" ] || die "misconfigured install: missing $VERSION_FILE"
    read -r FLOOR < "$VERSION_FILE" || true
    [ -n "$FLOOR" ] || die "misconfigured install: $VERSION_FILE names no version"
    PYTHON="$(resolve_python)"
    [ -n "$PYTHON" ] || die "no Python $FLOOR or newer on PATH. Install one, or point ADW_PYTHON at it."
    exec "$PYTHON" "$DIR/$script"
  fi
done
echo "$usage" >&2
exit 2
