from __future__ import annotations

import ast
import re

READ_ONLY_OPEN_MODE_CHARS = frozenset("rbtU")
SAFE_IMPORTS = frozenset({"json"})
PATH_IMPORT = ("pathlib", "Path")
SAFE_BUILTINS = frozenset({
    "all", "any", "bool", "bytes", "dict", "enumerate", "float", "int", "len", "list", "max", "min",
    "print", "range", "repr", "set", "sorted", "str", "sum", "tuple", "zip",
})
PATH_METHODS = {
    "absolute": "path",
    "as_posix": "text",
    "as_uri": "text",
    "exists": "value",
    "expanduser": "path",
    "glob": "value",
    "is_block_device": "value",
    "is_char_device": "value",
    "is_dir": "value",
    "is_fifo": "value",
    "is_file": "value",
    "is_mount": "value",
    "is_relative_to": "value",
    "is_socket": "value",
    "is_symlink": "value",
    "iterdir": "value",
    "lstat": "value",
    "match": "value",
    "read_bytes": "bytes",
    "read_text": "text",
    "relative_to": "path",
    "resolve": "path",
    "rglob": "value",
    "samefile": "value",
    "stat": "value",
    "with_name": "path",
    "with_suffix": "path",
}
PATH_CLASS_METHODS = {"cwd": "path", "home": "path"}
FILE_METHODS = {
    "isatty": "value",
    "read": "value",
    "readable": "value",
    "readline": "text",
    "readlines": "value",
    "seekable": "value",
    "tell": "value",
}
TEXT_METHODS = frozenset({
    "casefold", "capitalize", "count", "encode", "endswith", "find", "format", "index", "isalpha", "isdigit",
    "islower", "isspace", "istitle", "isupper", "join", "lower", "lstrip", "partition", "removeprefix",
    "removesuffix", "replace", "rfind", "rindex", "rjust", "rpartition", "rsplit", "rstrip", "split",
    "splitlines", "startswith", "strip", "swapcase", "title", "upper", "zfill",
})
BYTES_METHODS = frozenset({
    "decode", "endswith", "find", "index", "lower", "lstrip", "partition", "removeprefix", "removesuffix",
    "replace", "rfind", "rindex", "rpartition", "rsplit", "rstrip", "split", "splitlines", "startswith",
    "strip", "upper",
})
SAFE_LITERAL_TYPES = (str, bytes, int, float, complex, bool, type(None))
ASSIGNABLE_KINDS = frozenset({"bytes", "file", "path", "text", "value"})
SUSPICIOUS_BARE_LITERAL_RE = re.compile(r"(?:\b(?:write|exec|eval)\s*\(|__)")


def is_known_read_only_python(source: str) -> bool:
    try:
        tree = ast.parse(source, mode="exec")
    except (MemoryError, RecursionError, SyntaxError, TypeError, ValueError):
        return False
    return _ReadOnlyChecker().statements(tree.body)


class _ReadOnlyChecker:
    def __init__(self) -> None:
        self.bindings: dict[str, str] = {
            name: "builtin" for name in SAFE_BUILTINS
        }
        self.bindings["open"] = "open"
        self.protected_names = set(self.bindings) | {"Path", "json"}

    def statements(self, nodes: list[ast.stmt]) -> bool:
        return all(self.statement(node) for node in nodes)

    def statement(self, node: ast.stmt) -> bool:
        result = False
        if isinstance(node, ast.Expr):
            result = self.expression(node.value) is not None and not self.suspicious_bare_literal(node.value)
        elif isinstance(node, ast.Assert):
            result = self.expression(node.test) is not None and self._optional_expression(node.msg)
        elif isinstance(node, ast.Import):
            result = self.imports(node)
        elif isinstance(node, ast.ImportFrom):
            result = self.import_from(node)
        elif isinstance(node, ast.Pass):
            result = True
        elif isinstance(node, ast.Assign):
            result = self.assignment(node)
        elif isinstance(node, ast.If):
            result = (
                self.expression(node.test) is not None
                and self.statements(node.body)
                and self.statements(node.orelse)
            )
        elif isinstance(node, ast.With):
            result = self.with_statement(node)
        return result

    def suspicious_bare_literal(self, node: ast.expr) -> bool:
        if not isinstance(node, ast.Constant) or not isinstance(node.value, (str, bytes)):
            return False
        value = node.value.decode(errors="ignore") if isinstance(node.value, bytes) else node.value
        return bool(SUSPICIOUS_BARE_LITERAL_RE.search(value))

    def assignment(self, node: ast.Assign) -> bool:
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            return False
        name = node.targets[0].id
        kind = self.expression(node.value)
        if name in self.protected_names or kind not in ASSIGNABLE_KINDS:
            return False
        self.bindings[name] = kind
        return True

    def imports(self, node: ast.Import) -> bool:
        if len(node.names) != 1:
            return False
        alias = node.names[0]
        if alias.name not in SAFE_IMPORTS or alias.asname is not None:
            return False
        self.bindings[alias.name] = "json_module"
        return True

    def import_from(self, node: ast.ImportFrom) -> bool:
        if node.level or len(node.names) != 1:
            return False
        alias = node.names[0]
        if (node.module, alias.name) == PATH_IMPORT and alias.asname is None:
            self.bindings[alias.name] = "path_ctor"
            self.protected_names.add(alias.name)
            return True
        if node.module == "json" and alias.name in {"load", "loads"} and alias.asname is None:
            self.bindings[alias.name] = f"json_{alias.name}"
            self.protected_names.add(alias.name)
            return True
        return False

    def with_statement(self, node: ast.With) -> bool:
        if len(node.items) != 1:
            return False
        item = node.items[0]
        kind = self.expression(item.context_expr)
        if kind != "file" or not isinstance(item.optional_vars, ast.Name):
            return False
        name = item.optional_vars.id
        if name in self.protected_names:
            return False
        previous = self.bindings.get(name)
        self.bindings[name] = "file"
        result = self.statements(node.body)
        if previous is None:
            self.bindings.pop(name, None)
        else:
            self.bindings[name] = previous
        return result

    def expression(self, node: ast.expr) -> str | None:
        handlers = (
            (ast.Constant, self.constant),
            (ast.Name, self.name),
            (ast.Call, self.call),
            (ast.Attribute, self.attribute),
            ((ast.List, ast.Set, ast.Tuple), self.collection),
            (ast.Dict, self.dictionary),
            (ast.Subscript, self.subscript),
            (ast.JoinedStr, self.joined_string),
            (ast.UnaryOp, self.unary),
            ((ast.BinOp, ast.BoolOp), self.binary),
            (ast.Compare, self.compare),
            (ast.IfExp, self.conditional),
        )
        for node_type, handler in handlers:
            if isinstance(node, node_type):
                return handler(node)
        return None

    def constant(self, node: ast.Constant) -> str | None:
        return "value" if isinstance(node.value, SAFE_LITERAL_TYPES) else None

    def name(self, node: ast.Name) -> str | None:
        return self.bindings.get(node.id)

    def collection(self, node: ast.List | ast.Set | ast.Tuple) -> str | None:
        return "value" if all(self.expression(item) is not None for item in node.elts) else None

    def dictionary(self, node: ast.Dict) -> str | None:
        return "value" if all(
            key is not None and self.expression(key) is not None and self.expression(value) is not None
            for key, value in zip(node.keys, node.values)
        ) else None

    def subscript(self, node: ast.Subscript) -> str | None:
        return "value" if self.expression(node.value) is not None and self.slice(node.slice) else None

    def joined_string(self, node: ast.JoinedStr) -> str | None:
        return "value" if all(self.formatted_value(value) for value in node.values) else None

    def unary(self, node: ast.UnaryOp) -> str | None:
        return "value" if self.expression(node.operand) is not None else None

    def binary(self, node: ast.BinOp | ast.BoolOp) -> str | None:
        values = node.values if isinstance(node, ast.BoolOp) else (node.left, node.right)
        return "value" if all(self.expression(value) is not None for value in values) else None

    def compare(self, node: ast.Compare) -> str | None:
        values = (node.left, *node.comparators)
        return "value" if all(self.expression(value) is not None for value in values) else None

    def conditional(self, node: ast.IfExp) -> str | None:
        values = (node.test, node.body, node.orelse)
        return "value" if all(self.expression(value) is not None for value in values) else None

    def call(self, node: ast.Call) -> str | None:
        if not self.arguments(node.args, node.keywords):
            return None
        if isinstance(node.func, ast.Name):
            return self.named_call(node)
        if isinstance(node.func, ast.Attribute):
            return self.attribute_call(node)
        return None

    def named_call(self, node: ast.Call) -> str | None:
        func = node.func
        if not isinstance(func, ast.Name):
            return None
        kind = self.bindings.get(func.id)
        if kind == "path_ctor":
            return "path"
        if kind == "open":
            return "file" if self.read_open(node.args, node.keywords) else None
        if kind in {"json_load", "json_loads"}:
            return self.json_call(kind, node)
        return "value" if kind == "builtin" else None

    def json_call(self, kind: str, node: ast.Call) -> str | None:
        if len(node.args) != 1 or node.keywords:
            return None
        source_kind = self.expression(node.args[0])
        if kind == "json_load":
            return "value" if source_kind == "file" else None
        return "value" if source_kind in {"text", "bytes", "value"} else None

    def attribute_call(self, node: ast.Call) -> str | None:
        if not isinstance(node.func, ast.Attribute):
            return None
        method = self.attribute(node.func)
        if method is None:
            return None
        if method in {"json_load", "json_loads"}:
            return self.json_call(method, node)
        if method.startswith("path_"):
            return self.method_result(method[5:], node)
        return "value" if method.startswith(("file_", "text_", "bytes_")) else None

    def attribute(self, node: ast.Attribute) -> str | None:
        base = self.expression(node.value)
        if base == "json_module" and node.attr in {"load", "loads"}:
            return f"json_{node.attr}"
        if base == "path_ctor" and node.attr in PATH_CLASS_METHODS:
            return f"path_{node.attr}"
        methods = {
            "path": PATH_METHODS,
            "file": FILE_METHODS,
            "text": {name: "value" for name in TEXT_METHODS},
            "bytes": {name: "value" for name in BYTES_METHODS},
        }.get(base)
        if methods is None or node.attr not in methods:
            return None
        return f"{base}_{node.attr}"

    def method_result(self, method: str, node: ast.Call) -> str | None:
        if not self.arguments(node.args, node.keywords):
            return None
        if method == "read_text":
            return "text"
        if method == "read_bytes":
            return "bytes"
        return PATH_METHODS.get(method) or PATH_CLASS_METHODS.get(method)

    def arguments(self, args: list[ast.expr], keywords: list[ast.keyword]) -> bool:
        return all(self.expression(arg) is not None for arg in args) and all(
            keyword.arg is not None and self.expression(keyword.value) is not None for keyword in keywords
        )

    def read_open(self, args: list[ast.expr], keywords: list[ast.keyword]) -> bool:
        if not args or any(isinstance(arg, ast.Starred) for arg in args) or not self.expression(args[0]):
            return False
        mode = next((arg for arg in args[1:2]), None)
        for keyword in keywords:
            if keyword.arg == "mode":
                if mode is not None:
                    return False
                mode = keyword.value
            elif keyword.arg in {"buffering", "encoding", "errors", "newline", "closefd"}:
                if self.expression(keyword.value) is None:
                    return False
            else:
                return False
        if len(args) > 2 or mode is None:
            return mode is None and len(args) == 1
        return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and set(mode.value) <= READ_ONLY_OPEN_MODE_CHARS

    def slice(self, node: ast.slice) -> bool:
        if isinstance(node, ast.Slice):
            return all(value is None or self.expression(value) is not None for value in (node.lower, node.upper, node.step))
        return self.expression(node) is not None

    def formatted_value(self, node: ast.expr) -> bool:
        if not isinstance(node, ast.FormattedValue) or self.expression(node.value) is None:
            return False
        return node.format_spec is None or self.expression(node.format_spec) is not None

    def _optional_expression(self, node: ast.expr | None) -> bool:
        return node is None or self.expression(node) is not None
