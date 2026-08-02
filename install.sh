#!/usr/bin/env bash
set -eu

skill_dir="$(cd "$(dirname "$0")" && pwd)"
install_claude=1
install_codex=1
install_opencode=1
install_pi=1
assume_yes=0
claude_legacy=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --claude) install_claude=1 ;;
    --codex) install_codex=1 ;;
    --opencode) install_opencode=1 ;;
    --pi) install_pi=1 ;;
    --no-claude) install_claude=0 ;;
    --no-codex) install_codex=0 ;;
    --no-opencode) install_opencode=0 ;;
    --no-pi) install_pi=0 ;;
    --claude-legacy) install_claude=1; claude_legacy=1 ;;
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

mkdir -p "$HOME/.agents/skills"
ln -snf "$skill_dir" "$HOME/.agents/skills/agent-discipline-watcher"

if [ "$install_claude" -eq 1 ] && [ "$claude_legacy" -eq 1 ]; then
  mkdir -p "$HOME/.claude/skills"
  ln -snf "$skill_dir" "$HOME/.claude/skills/agent-discipline-watcher"
  backup_file "$HOME/.claude/settings.json"
  python3 "$skill_dir/hooks/merge-claude-settings.py" \
    --settings "$HOME/.claude/settings.json" \
    --skill-dir "$skill_dir"
  echo "Claude installed through the legacy path-based wiring. Moving the checkout breaks it."
elif [ "$install_claude" -eq 1 ]; then
  backup_file "$HOME/.claude/settings.json"
  python3 "$skill_dir/hooks/merge-claude-settings.py" \
    --settings "$HOME/.claude/settings.json" \
    --remove-legacy
  legacy_link="$HOME/.claude/skills/agent-discipline-watcher"
  if [ -L "$legacy_link" ] && [ "$(readlink "$legacy_link")" = "$skill_dir" ]; then
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
  python3 "$skill_dir/hooks/merge-codex-config.py" \
    --config "$HOME/.codex/config.toml" \
    --skill-dir "$skill_dir"
  echo "Codex hooks installed globally. Run /hooks in Codex to review and trust new or changed hooks."
fi

if [ "$install_opencode" -eq 1 ]; then
  mkdir -p "$HOME/.config/opencode/plugins"
  cp "$skill_dir/opencode/agent-discipline-watcher.ts" \
    "$HOME/.config/opencode/plugins/agent-discipline-watcher.ts"
fi

if [ "$install_pi" -eq 1 ]; then
  backup_file "$HOME/.pi/agent/settings.json"
  python3 "$skill_dir/hooks/merge-pi-settings.py" \
    --settings "$HOME/.pi/agent/settings.json" \
    --skill-dir "$skill_dir"
fi

mkdir -p "$HOME/.local/bin"
ln -snf "$skill_dir/bin/agent-discipline" "$HOME/.local/bin/agent-discipline"
ln -snf "$skill_dir/bin/adw-cli" "$HOME/.local/bin/adw-cli"

echo "installed agent-discipline-watcher"
