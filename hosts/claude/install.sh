#!/usr/bin/env bash
set -eu

host_dir="$(cd "$(dirname "$0")" && pwd)"
. "$host_dir/../common.sh"
adw_host_prelude

claude_home="$HOME/.claude"
rc_block='\n# >>> agent-discipline-watcher >>>\nexport PATH="$HOME/.local/bin:$PATH"\n# <<< agent-discipline-watcher <<<\n'

adw_backup_file "$claude_home/settings.json"

if [ "${ADW_CLAUDE_LEGACY:-0}" = "1" ]; then
  mkdir -p "$claude_home/skills"
  adw_replace_link "$claude_home/skills/agent-discipline-watcher" \
    "$ADW_SKILL_DIR/skills/agent-discipline-watcher"
  "$ADW_PYTHON" "$ADW_SKILL_DIR/hooks/merge-claude-settings.py" \
    --settings "$claude_home/settings.json" \
    --skill-dir "$ADW_SKILL_DIR"
  echo "Claude installed through the legacy path-based wiring from the isolated copy."
else
  "$ADW_PYTHON" "$ADW_SKILL_DIR/hooks/merge-claude-settings.py" \
    --settings "$claude_home/settings.json" \
    --remove-legacy
  legacy_link="$claude_home/skills/agent-discipline-watcher"
  if [ -L "$legacy_link" ]; then
    case "$(readlink "$legacy_link")" in
      */skills/agent-discipline-watcher) rm -f "$legacy_link" ;;
    esac
  fi
fi

mkdir -p "$HOME/.local/bin"
adw_replace_link "$HOME/.local/bin/adw-judge" "$ADW_SKILL_DIR/bin/adw-judge"

for rc_file in "$HOME/.zshrc" "$HOME/.bashrc"; do
  adw_append_rc_block "$rc_file" "$rc_block"
done

[ "${ADW_CLAUDE_LEGACY:-0}" = "1" ] && exit 0

marketplace="agent-discipline-watcher"
plugin="agent-discipline-watcher@$marketplace"
plugin_installed=0

if [ "${ADW_SKIP_PLUGIN:-0}" != "1" ] && command -v claude >/dev/null 2>&1; then
  echo "Clearing the stale Claude plugin cache. The ~/.adw settings tree stays."
  "$ADW_PYTHON" "$ADW_SKILL_DIR/hooks/claude_cache_nuke.py" || true

  # Unset because Claude Code refuses a nested session.
  if ! (unset CLAUDECODE; claude plugin marketplace add "michaelheichler/$marketplace") >/dev/null 2>&1; then
    (unset CLAUDECODE; claude plugin marketplace update "$marketplace") >/dev/null 2>&1 \
      || echo "Marketplace refresh failed. Trying the install anyway."
  fi

  if (unset CLAUDECODE; claude plugin install "$plugin") >/dev/null 2>&1; then
    plugin_installed=1
  elif (unset CLAUDECODE; claude plugin uninstall "$plugin" && claude plugin install "$plugin") >/dev/null 2>&1; then
    plugin_installed=1
  fi

  if [ "$plugin_installed" -eq 1 ]; then
    echo "Plugin reinstalled from a clean cache. Run /reload-plugins in Claude Code."
  fi
fi

if [ "$plugin_installed" -eq 0 ]; then
  cat <<'EOF'
Claude preset CLI installed as adw-judge. Hook wiring comes from the plugin:

  /plugin marketplace add michaelheichler/agent-discipline-watcher
  /plugin install agent-discipline-watcher@agent-discipline-watcher
  /reload-plugins
EOF
fi
