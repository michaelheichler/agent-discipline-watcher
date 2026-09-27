import sys


def _adapter(name: str):
    """Optional because a vendored runtime may lack Claude."""
    import importlib

    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def main() -> int:
    if not sys.flags.isolated or not sys.flags.no_site:
        print("adw-nuke requires Python -I -S. Use the installed adw-nuke command.", file=sys.stderr)
        return 2
    import importlib
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    runtime = importlib.import_module("lib.nuke_runtime")
    presets = _adapter("lib.claude_presets")
    steps = runtime.NukeSteps(
        claude_cache=_adapter("lib.claude_cache"),
        without_managed=getattr(presets, "without_managed", None),
        run_claude=runtime.run_claude,
    )
    return runtime.main(sys.argv[1:], steps=steps)


if __name__ == "__main__":
    raise SystemExit(main())
