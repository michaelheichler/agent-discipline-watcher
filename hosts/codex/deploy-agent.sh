#!/usr/bin/env bash
# Split out because tests must skip the venv and network cost.

adw_deploy_codex_test_writer() {
  local codex_home="$1"
  local skill_dir="$2"
  mkdir -p "$codex_home/agents"
  adw_replace_link \
    "$codex_home/agents/adw-test-writer.toml" \
    "$skill_dir/hosts/codex/agents/adw-test-writer.toml"
}
