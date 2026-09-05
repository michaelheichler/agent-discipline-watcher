#!/usr/bin/env bash
set -eu

host_dir="$(cd "$(dirname "$0")" && pwd)"
. "$host_dir/../common.sh"
adw_host_prelude

codex_home="${CODEX_HOME:-$HOME/.codex}"
runtime_dir="$HOME/.adw/runtime/codex"
runtime_venv="$runtime_dir/venv"
runtime_python="$runtime_venv/bin/python"
requirements="$ADW_SKILL_DIR/hooks/codex-runtime.requirements.txt"

# Removed because a stale link shadows the plugin.
rm -f "$codex_home/skills/agent-discipline-watcher"

adw_backup_file "$codex_home/config.toml"
# Kept because hooks.json is user-owned state.
adw_backup_file "$codex_home/hooks.json"

mkdir -p "$runtime_dir"
if [ ! -x "$runtime_python" ]; then
  "$ADW_PYTHON" -m venv "$runtime_venv"
fi
[ -x "$runtime_python" ] || {
  echo "install.sh: failed to create the ADW Codex runtime" >&2
  exit 2
}

manifest="$runtime_dir/requirements.txt"
if [ ! -f "$manifest" ] || ! cmp -s "$requirements" "$manifest"; then
  "$runtime_python" -m pip install --quiet --disable-pip-version-check --no-input \
    -r "$requirements"
  cp "$requirements" "$manifest"
fi

"$ADW_PYTHON" "$ADW_SKILL_DIR/hooks/merge-codex-config.py" \
  --config "$codex_home/config.toml" \
  --skill-dir "$ADW_SKILL_DIR" \
  --strip-only

"$ADW_PYTHON" "$ADW_SKILL_DIR/hooks/merge-codex-hooks.py" \
  --hooks-json "$codex_home/hooks.json" \
  --skill-dir "$ADW_SKILL_DIR"

echo "Codex hooks installed. Run /hooks in Codex to review and trust new or changed hooks."
