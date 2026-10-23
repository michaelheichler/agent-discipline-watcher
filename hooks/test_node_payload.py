from __future__ import annotations

from pathlib import Path

import pytest

import pre_bash


def verdict(command: str, cwd: Path | None = None) -> dict:
    payload = {"tool_input": {"command": command}}
    return pre_bash.run({**payload, "cwd": str(cwd)} if cwd else payload)


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (tmp_path / "hooks").mkdir()
    project.mkdir()
    for path in (project / "package.json", project / "a.json", tmp_path / "hooks" / "package.json"):
        path.write_text("{}", encoding="utf-8")
    (project / "evil.js").write_text("module.exports = 1\n", encoding="utf-8")
    return project


@pytest.mark.parametrize("command", [
    """node -p "require('./package.json').version\"""",
    """node -p "require('../hooks/package.json')['name']\"""",
    """node -e "console.log(require('{project}/a.json').compilerOptions.paths)\"""",
    """node -e "console.log(JSON.stringify(require('./package.json').scripts, null, 2));\"""",
    """node -p "Object.keys(require('./package.json').dependencies)\"""",
    """nodejs -p "require('./a.json')[0]\"""",
])
def test_a_json_require_of_a_real_json_file_passes(tmp_path: Path, command: str) -> None:
    project = _project(tmp_path)

    assert verdict(command.format(project=project), project) == {}


@pytest.mark.parametrize(("setup", "command"), [
    ("symlink", """node -p "require('./linked.json')\""""),
    ("symlink", """node -p "require('{project}/linked.json').version\""""),
    ("missing", """node -p "require('./missing.json')\""""),
    ("directory", """node -p "require('./folder.json')\""""),
    ("symlink", """ln -sf evil.js package.json && node -p "require('./package.json')\""""),
    ("none", """cd .. && node -p "require('./hooks/package.json').version\""""),
])
def test_a_json_require_that_can_load_code_blocks(tmp_path: Path, setup: str, command: str) -> None:
    project = _project(tmp_path)
    if setup == "symlink":
        (project / "linked.json").symlink_to(project / "evil.js")
    if setup == "directory":
        (project / "folder.json").mkdir()
        (project / "folder.json" / "index.js").write_text("module.exports = 1\n", encoding="utf-8")

    result = verdict(command.format(project=project), project)

    assert result.get("decision") == "block"
    assert "inline_interpreter_write" in result["reason"]


@pytest.mark.parametrize("command", [
    """node -p "require('fs.json')\"""",
    """node -p "require('./package.js').version\"""",
    """node -p "require('./package.json').version; require('fs').writeFileSync('x', 'y')\"""",
    """node -p "require('./package.json').constructor.constructor('return 1')()\"""",
    """node -p "require('./a.json' + '.js')\"""",
    """node -p "require(name + '.json')\"""",
    """node -p "require('./package.json')[key]\"""",
    """node -e "console.log(require('./package.json'), require('fs'))\"""",
    """perl -e "require('./package.json')\"""",
])
def test_a_json_require_with_any_other_code_still_blocks(command: str) -> None:
    result = verdict(command)

    assert result.get("decision") == "block"
    assert "inline_interpreter_write" in result["reason"]


@pytest.mark.parametrize("command", [
    """node -e "module.constructor._load('fs').writeFileSync('x', 'y')\"""",
    """node -e "process.getBuiltinModule('fs').writeFileSync('x', 'y')\"""",
    """node -e "process['getBuiltinModule']('fs')\"""",
    """node -e "process['getBuiltin' + 'Module']('fs')\"""",
    """node -e "const name = ['getBuiltin' + 'Module']; console.log(name)\"""",
    """node -e "globalThis[key]('fs')\"""",
    """node -e "process.binding('fs')\"""",
    """node -e "process.dlopen(module, 'x.node')\"""",
    """node -e "process.mainModule.children\"""",
    """node -e "import('fs').then(m => m.writeFileSync('x', 'y'))\"""",
    """node -e "Function('return 1')()\"""",
    """node -e "(0, eval)('1')\"""",
    """node -e "Reflect.apply(Math.max, null, [1])\"""",
])
def test_a_reflective_node_route_to_a_module_blocks(command: str) -> None:
    result = verdict(command)

    assert result.get("decision") == "block"
    assert "inline_interpreter_write" in result["reason"]


@pytest.mark.parametrize("command", [
    """node -e '[].map.\\u0063onstructor("return 1")()'""",
    """node -e '[].map.\\u{63}onstructor("return 1")()'""",
    """node -p "Math.\\u0063onstructor.name\"""",
])
def test_a_reflective_name_spelled_with_a_unicode_escape_blocks(command: str) -> None:
    result = verdict(command)

    assert result.get("decision") == "block"
    assert "inline_interpreter_write" in result["reason"]


@pytest.mark.parametrize("command", [
    "node -e 'console.log(1+2)'",
    """node -p 'JSON.parse("{\\"a\\": [1]}").a[0]'""",
    "node -p process.version",
    """node -p "process.versions['node']\"""",
    "node -e 'console.log([1, 2][0])'",
    """node -e 'console.log(/[a-z]/.test("x"))'""",
    """node -e '/[a-z]/.test("x")'""",
    """node -e 'console.log(/^[a-z]+$/.test("x"))'""",
    """node -e 'console.log(/[a-z]/.test("x")); // note'""",
    """node -e 'console.log(/[a-z]/.test("https://example.org"))'""",
    """node -e 'console.log(/[#a-z]/.test("x"))'""",
    """node -e 'if (true) /[a-z]/.test("x")'""",
])
def test_a_read_only_node_payload_passes(command: str) -> None:
    assert verdict(command) == {}


@pytest.mark.parametrize("command", [
    """node -e '/[a-z]/.test("x"); require("fs").writeFileSync("a", "b")'""",
    """node -e '/[a-z]/.test("x"); globalThis[k]("fs")'""",
    """node -e 'const h = 1 / 2; globalThis[k]("fs"); const q = 3 / 4'""",
    """node -e 'console.log("https://example.org"); globalThis[k]("fs")'""",
])
def test_a_regex_or_string_literal_does_not_hide_a_node_write(command: str) -> None:
    result = verdict(command)

    assert result.get("decision") == "block"
    assert "inline_interpreter_write" in result["reason"]
