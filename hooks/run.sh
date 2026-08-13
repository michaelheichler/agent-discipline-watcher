#!/bin/sh
set -eu

DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON=python3

DISPATCH="SessionStart:session_start.py UserPromptSubmit:prompt_submit.py PreToolUse:pre_tool.py PreCommit:pre_tool.py PostToolUse:record.py PostToolBatch:batch.py PostToolUseFailure:failure.py SubagentStart:subagent_start.py SubagentStop:subagent_stop.py Stop:stop.py"

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
    if [ -n "$script" ]
    then
      exec "$PYTHON" "$DIR/$script"
    fi
    exit 0
  fi
done
echo "$usage" >&2
exit 2
