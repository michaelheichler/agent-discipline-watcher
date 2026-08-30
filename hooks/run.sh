#!/bin/sh
set -eu

# CDPATH is unset first because an exported CDPATH makes cd echo the directory it landed in, which
# would end up glued into these paths.
unset CDPATH
DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION_FILE="$(cd "$DIR/.." && pwd)/.python-version"
FLOOR=""

DISPATCH="SessionStart:session_start.py Configure:configure.py UserPromptSubmit:prompt_submit.py PreToolUse:pre_tool.py PreCommit:pre_tool.py PostToolUse:record.py PostToolBatch:batch.py PostToolUseFailure:failure.py SubagentStart:subagent_start.py SubagentStop:subagent_stop.py Stop:stop.py SessionEnd:session_end.py JudgeReview:judge_review.py"

die() {
  echo "run.sh: $1" >&2
  exit 2
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
    . "$DIR/resolve-python.sh"
    read -r FLOOR < "$VERSION_FILE" || true
    [ -n "$FLOOR" ] || die "misconfigured install: $VERSION_FILE names no version"
    PYTHON="$(adw_resolve_python "$FLOOR")"
    [ -n "$PYTHON" ] || die "no Python $FLOOR or newer on PATH. Install one, or point ADW_PYTHON at it."
    exec "$PYTHON" "$DIR/$script"
  fi
done
echo "$usage" >&2
exit 2
