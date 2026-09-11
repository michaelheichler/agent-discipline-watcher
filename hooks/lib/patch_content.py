from pathlib import Path


def _find_lines(lines: list[str], before: list[str], cursor: int) -> int:
    for trimmed in (False, True):
        candidates = [line.rstrip() if trimmed else line for line in lines]
        wanted = [line.rstrip() if trimmed else line for line in before]
        for index in range(cursor, len(lines) - len(before) + 1):
            if candidates[index:index + len(before)] == wanted:
                return index
    raise ValueError("patch context is missing")


def _replace_hunk(lines: list[str], hunk: list[str], cursor: int) -> tuple[list[str], int]:
    before = [line[1:] for line in hunk if line.startswith((" ", "-"))]
    after = [line[1:] for line in hunk if line.startswith((" ", "+"))]
    if not before:
        return lines + after, len(lines) + len(after)
    index = _find_lines(lines, before, cursor)
    return lines[:index] + after + lines[index + len(before):], index + len(after)


def _updated_text(path: Path, body: list[str]) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    cursor = 0
    hunk: list[str] = []
    for line in [*body, "@@"]:
        if line.startswith("@@") or line == "*** End of File":
            if hunk:
                lines, cursor = _replace_hunk(lines, hunk, cursor)
                hunk = []
            if line.startswith("@@ "):
                cursor = _find_lines(lines, [line[3:]], cursor) + 1
        elif line.startswith((" ", "+", "-")):
            hunk.append(line)
        else:
            raise ValueError("unsupported patch line")
    return "\n".join(lines) + "\n"


def _file_content(operation: str, path: Path, body: list[str]) -> str | None:
    if operation == "Delete":
        return None
    if operation == "Add":
        if any(not line.startswith("+") for line in body):
            return None
        return "\n".join(line[1:] for line in body) + "\n"
    try:
        return _updated_text(path, body)
    except (OSError, UnicodeError, ValueError):
        return None


def projected_content(patch: str, cwd: Path) -> dict[str, str | None]:
    sections: list[tuple[str, str, list[str]]] = []
    for line in patch.splitlines():
        if line.startswith(("*** Add File: ", "*** Update File: ", "*** Delete File: ")):
            operation, path = line[4:].split(" File: ", 1)
            sections.append((operation, path.strip().strip('"'), []))
        elif sections and line not in {"*** Begin Patch", "*** End Patch"}:
            sections[-1][2].append(line)
    result: dict[str, str | None] = {}
    for operation, name, body in sections:
        path = Path(name).expanduser()
        path = path if path.is_absolute() else cwd / path
        destination = body[0][13:].strip().strip('"') if body and body[0].startswith("*** Move to: ") else None
        content = _file_content(operation, path, body[1:] if destination else body)
        result[name] = None if destination or name in result else content
        if destination:
            result[destination] = None if destination in result else content
    return result
