#!/usr/bin/env bash
# Shared because a per-host guard would drift.

adw_require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "${0##*/}: $name must be set by the installer router" >&2
    return 2
  fi
}

adw_backup_file() {
  [ -f "$1" ] || return 0
  cp "$1" "$1.agent-discipline-watcher.bak.$(date +%Y%m%d%H%M%S)"
}

adw_replace_link() {
  local link_path="$1"
  local target="$2"
  local legacy_target="${3:-}"
  if [ -L "$link_path" ]; then
    local current
    current="$(readlink "$link_path")"
    if [ "$current" != "$target" ] && [ "$current" != "$legacy_target" ]; then
      echo "refusing to replace foreign symlink: $link_path -> $current" >&2
      return 2
    fi
    rm -f "$link_path"
  elif [ -e "$link_path" ]; then
    mv "$link_path" "$link_path.agent-discipline-watcher.bak.$(date +%Y%m%d%H%M%S)"
  fi
  ln -s "$target" "$link_path"
}

adw_append_rc_block() {
  local rc_file="$1"
  local block="$2"
  grep -qF '# >>> agent-discipline-watcher >>>' "$rc_file" 2>/dev/null && return 0
  adw_backup_file "$rc_file"
  printf '%b' "$block" >> "$rc_file"
}

adw_remove_obsolete_links() {
  local link_path
  for link_path in "$HOME/.local/bin/agent-discipline" "$HOME/.local/bin/adw-cli"; do
    [ -L "$link_path" ] || continue
    case "$(readlink "$link_path")" in
      */agent-discipline-watcher/bin/agent-discipline|*/agent-discipline-watcher/bin/adw-cli)
        rm -f "$link_path"
        ;;
    esac
  done
}

adw_host_prelude() {
  adw_require_env ADW_SKILL_DIR || return 2
  adw_require_env ADW_PYTHON || return 2
  [ -d "$ADW_SKILL_DIR" ] || {
    echo "${0##*/}: ADW_SKILL_DIR does not exist: $ADW_SKILL_DIR" >&2
    return 2
  }
  [ -x "$ADW_PYTHON" ] || {
    echo "${0##*/}: ADW_PYTHON is not executable: $ADW_PYTHON" >&2
    return 2
  }
  # Cleared because a retired link outlives its host.
  adw_remove_obsolete_links
}
