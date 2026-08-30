#!/usr/bin/env bash
set -eu

host_dir="$(cd "$(dirname "$0")" && pwd)"
. "$host_dir/../common.sh"
adw_host_prelude

extension_installer="$ADW_SKILL_DIR/pi/install.sh"
[ -x "$extension_installer" ] || {
  echo "install.sh: the OMP extension installer is missing at $extension_installer" >&2
  exit 2
}

omp_args=(-y)
if [ -n "${PI_CODING_AGENT_DIR:-}" ]; then
  omp_args+=(--agent-dir "$PI_CODING_AGENT_DIR")
fi

# Skipped because the router already deployed it.
ADW_INSTALL_SKIP_DEPLOY=1 "$extension_installer" "${omp_args[@]}"
