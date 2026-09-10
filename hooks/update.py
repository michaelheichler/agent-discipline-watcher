import importlib
import sys
from pathlib import Path


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    runtime = importlib.import_module("lib.update_runtime")
    return runtime.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
