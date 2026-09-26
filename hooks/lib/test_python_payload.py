from __future__ import annotations

import pytest

from lib.python_payload import is_known_read_only_python


@pytest.mark.parametrize("payload", [
    "print(1)",
    "1 + 1",
    "open('x.txt').read()",
    "with open('x.txt', 'rb') as handle: print(handle.read())",
    "import json; json.load(open('x.json'))",
    "from pathlib import Path; Path('x.txt').read_text(encoding='utf-8')",
    "from pathlib import Path; print(Path('x.bin').read_bytes())",
    "from pathlib import Path; assert Path('x.txt').exists()",
    "from pathlib import Path; p = Path('x.txt'); print(p.exists()); print(repr(p.read_text()))",
    "from pathlib import (Path,); Path('x.txt').read_text()",
    "print('__'); print('.write(')",
    "from pathlib import Path; print(Path('x.bin').read_bytes().decode())",
    "from pathlib import Path; print(Path('x.txt').resolve().read_text())",
    "from pathlib import Path; print(Path('x.txt').expanduser().read_text())",
    "from pathlib import Path; print(Path.cwd().exists()); print(Path.home().exists())",
])
def test_known_read_only_python_is_accepted(payload: str) -> None:
    assert is_known_read_only_python(payload)


@pytest.mark.parametrize("payload", [
    "from pathlib import Path as P; P('x.txt').read_text()",
    "import pathlib; pathlib.Path('x.txt').read_text()",
    "from pathlib import Path; p = Path('x.txt'); reader = p.read_text; reader()",
    "from pathlib import Path; Path = Path",
    "from pathlib import Path; print = Path",
    "from pathlib import Path; getattr(Path('x.txt'), 'read_text')()",
    "from pathlib import Path; exec(Path('x.txt').read_text())",
    "from pathlib import Path; Path('x.txt').write_text('body')",
    "from pathlib import Path; Path('x.txt').write_bytes(b'body')",
    "from pathlib import Path; Path('x.txt').unknown()",
])
def test_unknown_or_write_capable_python_is_rejected(payload: str) -> None:
    assert not is_known_read_only_python(payload)


@pytest.mark.parametrize("payload", [
    "import json; d = json.load(open('x.json')); print(d.get('name'))",
    "import json; d = json.load(open('x.json')); print(d.get('name', 'none'))",
    "import json; d = json.loads('{}'); print(sorted(d.keys()))",
    "import json; d = json.load(open('x.json')); print([k for k, v in d.items()])",
    "import json; d = json.load(open('x.json')); print({v for v in d.values()})",
    "import json; d = json.load(open('x.json')); print({k: v for k, v in d.items() if v})",
    "import json; d = json.load(open('x.json')); print(d['hooks']['Stop'][0].get('command'))",
    "print([n * 2 for n in range(3)])",
    "import sys",
    "import json, sys; print(json.load(sys.stdin).get('tool_name'))",
    "import sys; print(sys.stdin.read())",
])
def test_json_reads_comprehensions_and_sys_are_accepted(payload: str) -> None:
    assert is_known_read_only_python(payload)


@pytest.mark.parametrize("payload", [
    "import json; d = json.load(open('x.json')); d.update({})",
    "import json; d = json.load(open('x.json')); d.clear()",
    "import json; d = json.load(open('x.json')); d.pop('x')",
    "import json; d = json.load(open('x.json')); d.get('x').write('y')",
    "import json, os",
    "import sys; sys.stdout.write('x')",
    "import sys; sys.exit(1)",
    "import sys; sys.modules",
    "import sys as s",
    "print([open('x', 'w') for n in range(3)])",
    "print({k: open('x', 'w') for k in range(3)})",
])
def test_json_and_sys_stay_read_only(payload: str) -> None:
    assert not is_known_read_only_python(payload)
