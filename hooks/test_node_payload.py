from __future__ import annotations

import pytest

import pre_bash


def verdict(command: str) -> dict:
    return pre_bash.run({"tool_input": {"command": command}})


@pytest.mark.parametrize("command", [
    """node -p "require('./package.json').version\"""",
    """node -p "require('../hooks/package.json')['name']\"""",
    """node -e "console.log(require('/abs/path/tsconfig.json').compilerOptions.paths)\"""",
    """node -e "console.log(JSON.stringify(require('./package.json').scripts, null, 2));\"""",
    """node -p "Object.keys(require('./package.json').dependencies)\"""",
    """nodejs -p "require('./a.json')[0]\"""",
])
def test_a_json_require_read_passes(command: str) -> None:
    assert verdict(command) == {}


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
    "node -e 'console.log(1+2)'",
    """node -p 'JSON.parse("{\\"a\\": [1]}").a[0]'""",
    "node -p process.version",
    """node -p "process.versions['node']\"""",
    "node -e 'console.log([1, 2][0])'",
])
def test_a_read_only_node_payload_passes(command: str) -> None:
    assert verdict(command) == {}
