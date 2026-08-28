#!/usr/bin/env bash
set -eu

skill_dir="$(cd "$(dirname "$0")" && pwd)"
install_claude=1
install_codex=1
install_omp=1
assume_yes=0
claude_legacy=0
picked_target=0

usage() {
  cat <<'EOF'
Usage: install.sh [options]

Install agent-discipline-watcher for Claude Code, Codex, and/or OMP.

Options:
  --claude            Install for Claude Code only
  --codex             Install for Codex only
  --omp               Install for OMP (oh-my-pi) only
  --no-claude         Skip Claude install
  --no-codex          Skip Codex install
  --no-omp            Skip OMP install
  --claude-legacy     Use legacy Claude path-based wiring (not recommended)
  -y                  Skip confirmation prompt
  -h, --help          Show this help

OMP-specific install/uninstall:
  ./pi/install.sh              Install OMP extension only
  ./pi/install.sh --remove     Remove OMP extension only

Environment:
  PI_CODING_AGENT_DIR   Override the OMP agent config directory
EOF
}

pick_target() {
  if [ "$picked_target" -eq 0 ]; then
    install_claude=0
    install_codex=0
    install_omp=0
    picked_target=1
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --claude) pick_target; install_claude=1 ;;
    --codex) pick_target; install_codex=1 ;;
    --omp) pick_target; install_omp=1 ;;
    --no-claude) install_claude=0 ;;
    --no-codex) install_codex=0 ;;
    --no-omp) install_omp=0 ;;
    --claude-legacy) pick_target; install_claude=1; claude_legacy=1 ;;
    -y) assume_yes=1 ;;
    -h|--help)
      usage
      exit 0
      ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [ "$assume_yes" -ne 1 ]; then
  printf "Install agent-discipline-watcher hooks? [y/N] "
  read -r answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *) echo "aborted"; exit 1 ;;
  esac
fi

backup_file() {
  [ -f "$1" ] || return 0
  cp "$1" "$1.agent-discipline-watcher.bak.$(date +%Y%m%d%H%M%S)"
}

installer_python=""
if [ "$install_claude" -eq 1 ] || [ "$install_codex" -eq 1 ]; then
  . "$skill_dir/hooks/resolve-python.sh"
  read -r installer_floor < "$skill_dir/.python-version"
  installer_python="$(adw_resolve_python "$installer_floor")"
  [ -n "$installer_python" ] || {
    echo "install.sh: no Python $installer_floor or newer on PATH. Install one, or point ADW_PYTHON at it." >&2
    exit 2
  }
fi

mkdir -p "$HOME/.agents/skills"
ln -snf "$skill_dir" "$HOME/.agents/skills/agent-discipline-watcher"

if [ "$install_claude" -eq 1 ] && [ "$claude_legacy" -eq 1 ]; then
  mkdir -p "$HOME/.claude/skills"
  ln -snf "$skill_dir/skills/agent-discipline-watcher" "$HOME/.claude/skills/agent-discipline-watcher"
  backup_file "$HOME/.claude/settings.json"
  "$installer_python" "$skill_dir/hooks/merge-claude-settings.py" \
    --settings "$HOME/.claude/settings.json" \
    --skill-dir "$skill_dir"
  echo "Claude installed through the legacy path-based wiring. Moving the checkout breaks it."
elif [ "$install_claude" -eq 1 ]; then
  backup_file "$HOME/.claude/settings.json"
  "$installer_python" "$skill_dir/hooks/merge-claude-settings.py" \
    --settings "$HOME/.claude/settings.json" \
    --remove-legacy
  legacy_link="$HOME/.claude/skills/agent-discipline-watcher"
  if [ -L "$legacy_link" ] && [ "$(readlink "$legacy_link")" = "$skill_dir/skills/agent-discipline-watcher" ]; then
    rm -f "$legacy_link"
  fi
  cat <<'EOF'
Claude is installed as a plugin, not by this script. Legacy watcher hooks were removed.
Run these commands inside Claude Code, then reload:

  /plugin marketplace add michaelheichler/agent-discipline-watcher
  /plugin install agent-discipline-watcher@agent-discipline-watcher
  /reload-plugins
EOF
fi

if [ "$install_codex" -eq 1 ]; then
  rm -f "$HOME/.codex/skills/agent-discipline-watcher"
  backup_file "$HOME/.codex/config.toml"
  backup_file "$HOME/.codex/hooks.json"
  rm -f "$HOME/.codex/hooks.json"
  "$installer_python" "$skill_dir/hooks/merge-codex-config.py" \
    --config "$HOME/.codex/config.toml" \
    --skill-dir "$skill_dir"
  echo "Codex hooks installed globally. Run /hooks in Codex to review and trust new or changed hooks."
fi

if [ "$install_omp" -eq 1 ]; then
  omp_args=(-y)
  if [ -n "${PI_CODING_AGENT_DIR:-}" ]; then
    omp_args+=(--agent-dir "$PI_CODING_AGENT_DIR")
  fi
  "$skill_dir/pi/install.sh" "${omp_args[@]}"
fi

if [ -f "$skill_dir/bin/agent-discipline" ]; then
  mkdir -p "$HOME/.local/bin"
  ln -snf "$skill_dir/bin/agent-discipline" "$HOME/.local/bin/agent-discipline"
  ln -snf "$skill_dir/bin/adw-cli" "$HOME/.local/bin/adw-cli"
fi

rc_block='\n# >>> agent-discipline-watcher >>>\nexport PATH="$HOME/.local/bin:$PATH"\n[ -f "$HOME/.agents/skills/agent-discipline-watcher/scripts/adw-completion.bash" ] && . "$HOME/.agents/skills/agent-discipline-watcher/scripts/adw-completion.bash"\n# <<< agent-discipline-watcher <<<\n'
for rc_file in "$HOME/.zshrc" "$HOME/.bashrc"; do
  if ! grep -qF '# >>> agent-discipline-watcher >>>' "$rc_file" 2>/dev/null; then
    backup_file "$rc_file"
    printf '%b' "$rc_block" >> "$rc_file"
  fi
done

echo "installed agent-discipline-watcher"
