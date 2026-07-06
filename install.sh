#!/usr/bin/env bash
set -eu

skill_dir="$(cd "$(dirname "$0")" && pwd)"
install_claude=1
install_codex=1
install_pi=1
assume_yes=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --claude) install_claude=1 ;;
    --codex) install_codex=1 ;;
    --pi) install_pi=1 ;;
    --no-claude) install_claude=0 ;;
    --no-codex) install_codex=0 ;;
    --no-pi) install_pi=0 ;;
    -y) assume_yes=1 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
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

if [ "$install_claude" -eq 1 ]; then
  mkdir -p "$HOME/.claude/skills"
  ln -snf "$skill_dir" "$HOME/.claude/skills/agent-discipline-watcher"
  backup_file "$HOME/.claude/settings.json"
  python3 "$skill_dir/hooks/merge-claude-settings.py" \
    --settings "$HOME/.claude/settings.json" \
    --skill-dir "$skill_dir"
fi

if [ "$install_codex" -eq 1 ]; then
  mkdir -p "$HOME/.codex/skills"
  ln -snf "$skill_dir" "$HOME/.codex/skills/agent-discipline-watcher"
  backup_file "$HOME/.codex/config.toml"
  backup_file "$HOME/.codex/hooks.json"
  rm -f "$HOME/.codex/hooks.json"
  python3 "$skill_dir/hooks/merge-codex-config.py" \
    --config "$HOME/.codex/config.toml" \
    --skill-dir "$skill_dir"
  echo "Codex hooks installed globally. Run /hooks in Codex to review and trust new or changed hooks."
fi

if [ "$install_pi" -eq 1 ]; then
  backup_file "$HOME/.pi/agent/settings.json"
  python3 "$skill_dir/hooks/merge-pi-settings.py" \
    --settings "$HOME/.pi/agent/settings.json" \
    --skill-dir "$skill_dir"
fi

mkdir -p "$HOME/.local/bin"
ln -snf "$skill_dir/bin/agent-discipline" "$HOME/.local/bin/agent-discipline"

echo "installed agent-discipline-watcher"
