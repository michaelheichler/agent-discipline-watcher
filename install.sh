#!/usr/bin/env bash
set -eu

repo_dir="$(cd "$(dirname "$0")" && pwd)"
install_dir="${ADW_INSTALL_DIR:-$HOME/.adw/install/agent-discipline-watcher}"
picker_args=()
dry_run=0

usage() {
  cat <<'EOF'
Usage: install.sh [options]

Choose which agent-discipline-watcher host runtimes to install. With no host
flag this opens an interactive picker. Arrows move, space toggles, Enter
installs, and a mouse click selects a row.

Options:
  --claude            Install the Claude preset CLI and clear legacy hooks
  --claude-legacy     Use the legacy path-based Claude wiring (not recommended)
  --codex             Install the Codex runtime
  --omp               Install the OMP extension
  -y                  Accepted and ignored, because the picker is the prompt
  --list              Print the installable host names and exit
  --dry-run           Print the installers a choice would run, and write nothing
  -h, --help          Show this help

Environment:
  ADW_INSTALL_DIR       Override the isolated ADW install root
  PI_CODING_AGENT_DIR   Override the OMP agent config directory

Each host installer writes only under ~/.adw and its own host directory.
Choosing nothing leaves the disk untouched.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --claude|--codex|--omp) picker_args+=(--host "${1#--}") ;;
    --claude-legacy) picker_args+=(--host claude); export ADW_CLAUDE_LEGACY=1 ;;
    --list) picker_args+=(--list) ;;
    --dry-run) dry_run=1 ;;
    -y) ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

. "$repo_dir/hooks/resolve-python.sh"
read -r installer_floor < "$repo_dir/.python-version"
installer_python="$(adw_resolve_python "$installer_floor")"
[ -n "$installer_python" ] || {
  echo "install.sh: no Python $installer_floor or newer on PATH. Install one, or point ADW_PYTHON at it." >&2
  exit 2
}

# First, because cancelling must touch no disk.
set +e
chosen="$("$installer_python" "$repo_dir/hooks/host_picker.py" "${picker_args[@]+"${picker_args[@]}"}")"
picker_status=$?
set -e
[ "$picker_status" -eq 0 ] || exit "$picker_status"

case " ${picker_args[*]+${picker_args[*]}} " in
  *" --list "*)
    printf '%s\n' "$chosen"
    exit 0
    ;;
esac

[ -n "$chosen" ] || {
  echo "No host selected. Nothing was written."
  exit 0
}

if [ "$dry_run" -eq 1 ]; then
  for host_name in $chosen; do
    echo "$install_dir/hosts/$host_name/install.sh"
  done
  exit 0
fi

"$installer_python" "$repo_dir/hooks/install_runtime.py" \
  --source "$repo_dir" \
  --destination "$install_dir" >/dev/null

for host_name in $chosen; do
  host_installer="$install_dir/hosts/$host_name/install.sh"
  [ -x "$host_installer" ] || {
    echo "install.sh: no installer for $host_name at $host_installer" >&2
    exit 2
  }
  ADW_SKILL_DIR="$install_dir" ADW_PYTHON="$installer_python" \
    ADW_CLAUDE_LEGACY="${ADW_CLAUDE_LEGACY:-0}" "$host_installer"
done

echo "installed agent-discipline-watcher for: $(echo "$chosen" | tr '\n' ' ')"
