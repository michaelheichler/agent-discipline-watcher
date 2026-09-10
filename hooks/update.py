import sys


def main() -> int:
    if not sys.flags.isolated or not sys.flags.no_site:
        print("adw update requires Python -I -S. Use the installed adw command.", file=sys.stderr)
        return 2
    import importlib
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    runtime = importlib.import_module("lib.update_runtime")
    return runtime.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
