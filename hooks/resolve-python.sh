adw_python_version_key() {
  adw_version="$1"
  adw_saved_ifs="$IFS"
  IFS=.
  set -- $adw_version
  IFS="$adw_saved_ifs"
  [ "$#" -ge 2 ] && [ "$#" -le 3 ] || return 1
  adw_major="$1"
  adw_minor="$2"
  adw_patch="${3:-0}"
  for adw_part in "$adw_major" "$adw_minor" "$adw_patch"
  do
    case "$adw_part" in
      ''|*[!0-9]*) return 1 ;;
    esac
  done
  printf '%06d%06d%06d\n' "$adw_major" "$adw_minor" "$adw_patch"
}

adw_python_key_at_least() {
  [ "$1" = "$2" ] || [ "$1" \> "$2" ]
}

adw_resolve_python() {
  adw_floor="$1"
  adw_floor_key="$(adw_python_version_key "$adw_floor")" || return 0
  if [ -n "${ADW_PYTHON:-}" ]
  then
    adw_override="$(command -v "$ADW_PYTHON" 2>/dev/null || true)"
    adw_version="$("$adw_override" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || true)"
    adw_key="$(adw_python_version_key "$adw_version")" || return 0
    adw_python_key_at_least "$adw_key" "$adw_floor_key" && printf '%s\n' "$adw_override"
    return 0
  fi
  adw_best=""
  adw_best_key=""
  adw_saved_ifs="$IFS"
  IFS=:
  set -- $PATH
  IFS="$adw_saved_ifs"
  for adw_dir in "$@"
  do
    [ -n "$adw_dir" ] || adw_dir="."
    for adw_candidate in "$adw_dir"/python3.[0-9][0-9] "$adw_dir"/python3.[0-9] "$adw_dir"/python3 "$adw_dir"/python
    do
      [ -x "$adw_candidate" ] || continue
      adw_version="$("$adw_candidate" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || true)"
      adw_key="$(adw_python_version_key "$adw_version")" || continue
      adw_python_key_at_least "$adw_key" "$adw_floor_key" || continue
      if [ -z "$adw_best_key" ] || [ "$adw_key" \> "$adw_best_key" ]
      then
        adw_best="$adw_candidate"
        adw_best_key="$adw_key"
      fi
    done
  done
  if [ -n "$adw_best" ]
  then
    printf '%s\n' "$adw_best"
  fi
  return 0
}
