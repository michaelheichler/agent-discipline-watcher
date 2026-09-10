import json
import sys

from lib.omp_review import run


def main() -> None:
    try:
        raw = sys.stdin.buffer.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise ValueError("OMP review bridge input exceeds 256 KiB")
        result = run(json.loads(raw))
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=True))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:900]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
