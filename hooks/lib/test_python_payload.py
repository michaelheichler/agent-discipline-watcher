from __future__ import annotations

import pytest

from lib.python_payload import is_known_read_only_python, python_rejection


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


@pytest.mark.parametrize(("payload", "named"), [
    ("from pathlib import Path; Path('x.txt').write_text('body')", "Path('x.txt').write_text('body')\" on line 1"),
    ("print(1)\nopen('x.txt', 'w').write('y')", "Call \"open('x.txt', 'w')\" on line 2"),
    ("x = 1\nimport os", "Import \"import os\" on line 2"),
    ("run_user_supplied_code()", "Call \"run_user_supplied_code()\" on line 1"),
    ("print(secret)", "Name \"secret\" on line 1"),
])
def test_rejection_names_the_first_rejected_node(payload: str, named: str) -> None:
    assert named in python_rejection(payload, isolated=True)


def test_read_only_python_has_no_rejection() -> None:
    assert python_rejection("print(1)", isolated=True) == ""


@pytest.mark.parametrize("payload", [
    "import json; d = json.load(open('x.json')); print(sum(1 for p in d['a'] if p.startswith('x')))",
    "import json; d = json.load(open('x.json')); print([p.lower() for p in d['a']])",
    "import json; d = json.load(open('x.json')); print(d['a'].count('x'), d['a'].index('y'))",
    "import json; d = json.load(open('x.json')); print(d['name'].split('/')[-1].strip())",
])
def test_json_element_text_methods_are_accepted(payload: str) -> None:
    assert is_known_read_only_python(payload)


@pytest.mark.parametrize("mutator", ["append", "clear", "extend", "insert", "pop", "remove", "setdefault", "sort", "update"])
def test_json_element_mutators_stay_rejected(mutator: str) -> None:
    assert not is_known_read_only_python(f"import json; d = json.load(open('x.json')); d['a'].{mutator}(1)")


@pytest.mark.parametrize("payload", [
    "import re,sys,html; print(html.unescape(re.sub(r'<[^>]+>', '', sys.stdin.read())))",
    "import re; m = re.search(r'v(\\d+)', open('x.txt').read()); print(m.group(1) if m else '')",
    "import re; print([m.start() for m in re.finditer('a', 'banana', re.I | re.M)])",
    "import re; pattern = re.compile('a+'); print(pattern.findall('aab'))",
    "import math; print(math.sqrt(4), math.pi)",
    "import itertools; print(list(itertools.islice(open('x.txt'), 3)))",
    "from itertools import chain; print(list(chain([1], [2])))",
    "from collections import Counter; c = Counter(open('x.txt').read().split()); print(c.most_common(3))",
    "from collections import OrderedDict; print(OrderedDict(a=1).get('a'))",
    "d = {'a': 1}\nfor key, value in d.items():\n    print(key, value, d.get(key))",
    "import datetime; print(datetime.datetime.now().isoformat(), datetime.date.today().year)",
    "from datetime import datetime, timedelta; print(datetime.now().strftime('%F'), timedelta(days=1).total_seconds())",
    "import hashlib; print(hashlib.sha256(open('x.bin', 'rb').read()).hexdigest())",
    "import tomllib; print(tomllib.load(open('x.toml', 'rb')).get('project'))",
    "import ast; ast.parse(open('x.py').read())",
    "import os.path; print(os.path.exists('x'), os.path.getsize('x'), os.path.splitext('a.b'))",
    "from os.path import basename, dirname, isdir, isfile, join; print(join(dirname('a/b'), basename('c')), isfile('x'), isdir('y'))",
    "from os import path; print(path.isfile('x'))",
    "from pathlib import Path, PurePath; print(PurePath('a/b').as_posix() if Path('x').exists() else 1)",
    "import sys; print(sys.version, sys.platform)",
])
def test_pure_stdlib_modules_are_accepted(payload: str) -> None:
    assert is_known_read_only_python(payload)


@pytest.mark.parametrize("payload", [
    "import os",
    "import subprocess",
    "import shutil",
    "import os.path; os.remove('x')",
    "import os.path; os.system('rm x')",
    "import os.path; os.path.os.remove('x')",
    "from os import remove",
    "from os import system",
    "from os.path import os",
    "import subprocess; subprocess.run(['rm', 'x'])",
    "from shutil import copy",
    "import re as r",
    "import collections; collections.defaultdict(list)",
    "import re; re.purge()",
    "import ast; ast.literal_eval('1').write('x')",
    "from functools import reduce; reduce(open, ['x.txt', 'w'])",
    "import functools; print('x', file=functools.reduce({'f': open}.get('f'), ['p.py', 'w']))",
    "import functools",
    "print(sorted(['x.txt'], key=open))",
    "import hashlib; h = hashlib.sha256(); h.update(open('x', 'w'))",
    "from pathlib import Path; d = {'a': Path('x')}; d['a'].replace('y')",
    "from pathlib import Path; d = {'a': Path('x')}; d.get('a').replace('y')",
    "from collections import OrderedDict; from pathlib import Path; OrderedDict(a=Path('x')).get('a').replace('y')",
    "from collections import Counter; from pathlib import Path\nfor path in Counter([Path('x')]):\n    path.replace('y')",
    "import json; d = json.load(open('x.json')); d.get('a').rename('y')",
])
def test_os_and_subprocess_stay_rejected(payload: str) -> None:
    assert not is_known_read_only_python(payload)


def test_json_dumps_is_accepted_but_default_callable_is_not() -> None:
    assert is_known_read_only_python("import json; print(json.dumps(json.load(open('x.json')), indent=2, sort_keys=True))")
    assert is_known_read_only_python("from json import dumps; print(dumps({'a': 1}))")
    assert not is_known_read_only_python("import json; print(json.dumps({}, default=open))")
    assert not is_known_read_only_python("import json; print(json.dumps({}, default=str))")
    assert not is_known_read_only_python("import json; print(json.dumps({}, cls=dict))")
    assert not is_known_read_only_python("import json; json.dump({}, open('x.json', 'w'))")


@pytest.mark.parametrize("payload", [
    "import json; d = json.load(open('x.json')); print(max(d, key=lambda k: len(d[k])))",
    "import json; d = json.load(open('x.json')); print(sorted(d.items(), key=lambda kv: kv[0].lower()))",
    "print(min(['b', 'a'], key=lambda word: word.upper()))",
])
def test_lambda_key_is_accepted_only_for_sort_helpers(payload: str) -> None:
    assert is_known_read_only_python(payload)


@pytest.mark.parametrize("payload", [
    "print(sorted(['x.txt'], key=lambda name: open(name, 'w')))",
    "print(sorted(['x.txt'], key=lambda open: open))",
    "print(sorted(['x.txt'], key=lambda *names: names))",
    "print(sorted(['x.txt'], key=lambda name, mode='w': name))",
    "f = lambda name: name",
    "print(list(['x'], key=lambda name: name))",
    "from functools import reduce; print(reduce(lambda a, b: a + b, [1, 2]))",
    "print(sorted(['x.txt'], reverse=lambda name: name))",
    "from pathlib import Path; print(sorted([Path('x')], key=lambda path: path.write_text('y')))",
    "print(sorted(['x']), lambda name: name)",
])
def test_lambda_outside_a_sort_key_or_with_a_write_body_is_rejected(payload: str) -> None:
    assert not is_known_read_only_python(payload)


@pytest.mark.parametrize("payload", [
    "d = {}; d['k'] = 1; print(d)",
    "counts = {}\nfor word in open('x.txt').read().split():\n    counts[word] = counts.get(word, 0) + 1",
    "rows = [0, 0]; rows[1] = 5; print(rows)",
    "counts = {w: 0 for w in ['a']}; counts['a'] += 1",
    "total = 0\nfor n in range(3):\n    total += n",
])
def test_item_assignment_to_a_local_literal_is_accepted(payload: str) -> None:
    assert is_known_read_only_python(payload)


@pytest.mark.parametrize("payload", [
    "import json; d = json.load(open('x.json')); d['k'] = 1",
    "import sys; sys.argv[0] = 'x'",
    "d = {}; d = open('x.txt'); d['k'] = 1",
    "d = {}; d['k']['j'] = 1",
    "d = {}; d[open('x', 'w')] = 1",
    "d = {}; d['k'] = open('x', 'w')",
    "secret += 1",
    "print += 1",
    "d = {}\ndef f():\n    d['k'] = 1",
])
def test_item_assignment_outside_a_local_literal_is_rejected(payload: str) -> None:
    assert not is_known_read_only_python(payload)


def test_unassigned_name_message_suggests_the_fix() -> None:
    rejection = python_rejection("import json; d = json.load(open(p)); print(d)", isolated=True)

    assert "Name \"p\" on line 1, which is never assigned in this payload. Define it or inline the value" in rejection


def test_rejected_known_name_has_no_unassigned_hint() -> None:
    assert "never assigned" not in python_rejection("open('x.txt', 'w')", isolated=True)
