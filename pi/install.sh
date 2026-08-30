#!/usr/bin/env bash
set -eu

checkout_dir="$(cd "$(dirname "$0")/.." && pwd)"
install_dir="${ADW_INSTALL_DIR:-$HOME/.adw/install/agent-discipline-watcher}"
legacy_install_dir="${ADW_LEGACY_INSTALL_DIR:-$checkout_dir}"
skill_dir="$checkout_dir"
omp_agent_dir="${PI_CODING_AGENT_DIR:-$HOME/.omp/agent}"
extension_name="agent-discipline-watcher"
extension_src="$skill_dir/pi/extensions/$extension_name"
extension_link="$omp_agent_dir/extensions/$extension_name"
runtime_link="$HOME/.agents/skills/$extension_name"
remove=0
assume_yes=0

usage() {
  cat <<'EOF'
Usage: pi/install.sh [options]

Install or remove agent-discipline-watcher for OMP (oh-my-pi).

Options:
  --remove            Uninstall the extension from this OMP agent directory
  --agent-dir DIR     OMP agent directory (default: $PI_CODING_AGENT_DIR or ~/.omp/agent)
  -y                  Skip confirmation prompt
  -h, --help          Show this help

Environment:
  PI_CODING_AGENT_DIR   Override the OMP agent config directory
  ADW_INSTALL_DIR       Override the isolated ADW install root

After install, restart OMP or pass --extension to load the extension immediately.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --remove) remove=1 ;;
    --agent-dir)
      shift
      [ "$#" -gt 0 ] || { echo "--agent-dir requires a path" >&2; exit 2; }
      omp_agent_dir="$1"
      ;;
    -y) assume_yes=1 ;;
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

if [ ! -f "$extension_src/index.ts" ]; then
  echo "extension source missing: $extension_src/index.ts" >&2
  exit 1
fi

if [ "$assume_yes" -ne 1 ]; then
  if [ "$remove" -eq 1 ]; then
    printf "Remove agent-discipline-watcher from OMP (%s)? [y/N] " "$omp_agent_dir"
  else
    printf "Install agent-discipline-watcher into OMP (%s)? [y/N] " "$omp_agent_dir"
  fi
  read -r answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *) echo "aborted"; exit 1 ;;
  esac
fi

if [ "$remove" -eq 0 ] && [ "${ADW_INSTALL_SKIP_DEPLOY:-0}" -ne 1 ]; then
  . "$checkout_dir/hooks/resolve-python.sh"
  read -r installer_floor < "$checkout_dir/.python-version"
  installer_python="$(adw_resolve_python "$installer_floor")"
  [ -n "$installer_python" ] || {
    echo "pi/install.sh: no Python $installer_floor or newer on PATH. Install one, or point ADW_PYTHON at it." >&2
    exit 2
  }
  "$installer_python" "$checkout_dir/hooks/install_runtime.py" \
    --source "$checkout_dir" \
    --destination "$install_dir" >/dev/null
fi
if [ "$remove" -eq 0 ]; then
  skill_dir="$install_dir"
fi
extension_src="$skill_dir/pi/extensions/$extension_name"
extension_link="$omp_agent_dir/extensions/$extension_name"

backup_file() {
  [ -f "$1" ] || return 0
  cp "$1" "$1.agent-discipline-watcher.bak.$(date +%Y%m%d%H%M%S)"
}

replace_link() {
  local link_path="$1"
  local target="$2"
  local legacy_target="${3:-}"
  if [ -L "$link_path" ]; then
    local current_target="$(readlink "$link_path")"
    if [ "$current_target" != "$target" ] && [ "$current_target" != "$legacy_target" ]; then
      echo "refusing to replace foreign symlink: $link_path -> $current_target" >&2
      return 2
    fi
    rm -f "$link_path"
  elif [ -e "$link_path" ]; then
    local backup_path="$link_path.agent-discipline-watcher.bak.$(date +%Y%m%d%H%M%S)"
    mv "$link_path" "$backup_path"
  fi
  ln -s "$target" "$link_path"
}

resolve_installer_python() {
  . "$skill_dir/hooks/resolve-python.sh"
  read -r installer_floor < "$skill_dir/.python-version"
  installer_python="$(adw_resolve_python "$installer_floor")"
  [ -n "$installer_python" ] || {
    echo "pi/install.sh: no Python $installer_floor or newer on PATH. Install one, or point ADW_PYTHON at it." >&2
    return 1
  }
  printf '%s\n' "$installer_python"
}

if [ "$remove" -eq 1 ]; then
  if [ -L "$extension_link" ]; then
    if [ "$(readlink "$extension_link")" = "$extension_src" ] || [ "$(readlink "$extension_link")" = "$install_dir/pi/extensions/$extension_name" ]; then
      rm -f "$extension_link"
    else
      echo "warning: $extension_link is a symlink to something else; leaving it in place" >&2
    fi
  elif [ -e "$extension_link" ]; then
    echo "warning: $extension_link is not a symlink installed by this script; leaving it in place" >&2
  fi
  if [ -L "$runtime_link" ] && {
    [ "$(readlink "$runtime_link")" = "$skill_dir" ] ||
    [ "$(readlink "$runtime_link")" = "$install_dir" ];
  }; then
    rm -f "$runtime_link"
  fi
  if [ -f "$omp_agent_dir/settings.json" ]; then
    backup_file "$omp_agent_dir/settings.json"
    installer_python="$(resolve_installer_python)"
    "$installer_python" "$skill_dir/pi/merge-settings.py" \
      --settings "$omp_agent_dir/settings.json" \
      --skill-dir "$skill_dir" \
      --remove
  fi
  echo "Removed agent-discipline-watcher from $omp_agent_dir"
  exit 0
fi

mkdir -p "$omp_agent_dir/extensions"
mkdir -p "$HOME/.agents/skills"
mkdir -p "$(dirname "$extension_link")"
replace_link "$runtime_link" "$skill_dir" "$legacy_install_dir"
replace_link "$extension_link" "$extension_src" "$legacy_install_dir/pi/extensions/$extension_name"
backup_file "$omp_agent_dir/settings.json"
installer_python="$(resolve_installer_python)"
"$installer_python" "$skill_dir/pi/merge-settings.py" \
  --settings "$omp_agent_dir/settings.json" \
  --skill-dir "$skill_dir"
echo "OMP extension linked at $extension_link"
echo "OMP extension registered in $omp_agent_dir/settings.json"
echo "Restart omp or pass --extension to load the extension immediately."
