if [ -n "${ZSH_VERSION:-}" ]; then
  autoload -Uz +X compinit && compinit
  autoload -Uz +X bashcompinit && bashcompinit
fi
_adw_cli() {
  local cur="${COMP_WORDS[COMP_CWORD]}" prev="${COMP_WORDS[COMP_CWORD-1]}"
  if [ "$prev" = "--format" ]; then
    COMPREPLY=($(compgen -W "text md json" -- "$cur")); return
  fi
  case "${COMP_WORDS[1]:-}" in
    review) COMPREPLY=($(compgen -W "--commits --format --output --gitnexus" -- "$cur")) ;;
    search) COMPREPLY=($(compgen -W "--commits --findings --code" -- "$cur")) ;;
    *) COMPREPLY=($(compgen -W "review search" -- "$cur")) ;;
  esac
}
complete -o default -F _adw_cli adw-cli
