#!/usr/bin/env bash
# Split out because tests must skip the venv and network cost.

adw_deploy_codex_test_writer() {
  # Copied, because Codex rejects a symlinked role file at spawn.
  local codex_home="$1"
  local skill_dir="$2"
  local role_path="$codex_home/agents/adw-test-writer.toml"
  local source="$skill_dir/hosts/codex/agents/adw-test-writer.toml"
  mkdir -p "$codex_home/agents"
  if [ -L "$role_path" ]; then
    case "$(readlink "$role_path")" in
      */agent-discipline-watcher/hosts/codex/agents/adw-test-writer.toml) rm -f "$role_path" ;;
      *)
        echo "refusing to replace foreign symlink: $role_path -> $(readlink "$role_path")" >&2
        return 2
        ;;
    esac
  elif [ -e "$role_path" ] && ! grep -qx 'name = "adw-test-writer"' "$role_path"; then
    echo "refusing to replace foreign role file: $role_path" >&2
    return 2
  fi
  cp "$source" "$role_path.adw-tmp.$$" && mv -f "$role_path.adw-tmp.$$" "$role_path"
}
