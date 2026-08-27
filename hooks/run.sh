#!/bin/sh
set -eu

DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON=python3

DISPATCH="SessionStart:session_start.py UserPromptSubmit:prompt_submit.py PreToolUse:pre_tool.py PreCommit:pre_tool.py PostToolUse:record.py PostToolBatch:batch.py PostToolUseFailure:failure.py SubagentStart:subagent_start.py SubagentStop:subagent_stop.py Stop:stop.py JudgeReview:judge_review.py"

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
    if ! command -v "$PYTHON" >/dev/null 2>&1 || [ ! -f "$DIR/$script" ]
    then
      echo "run.sh: misconfigured install: missing $PYTHON or $DIR/$script" >&2
      exit 2
    fi
    exec "$PYTHON" "$DIR/$script"
  fi
done
echo "$usage" >&2
exit 2
