from __future__ import annotations

import ast
import re

from .python_imports import imports_are_trusted

Kind = str | tuple[str, tuple["Kind", ...]]
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
    "glob": ("sequence", ("path",)),
    "is_block_device": "value",
    "is_char_device": "value",
    "is_dir": "value",
    "is_fifo": "value",
    "is_file": "value",
    "is_mount": "value",
    "is_relative_to": "value",
    "is_socket": "value",
    "is_symlink": "value",
    "iterdir": ("sequence", ("path",)),
    "lstat": "value",
    "match": "value",
    "read_bytes": "bytes",
    "read_text": "text",
    "relative_to": "path",
    "resolve": "path",
    "rglob": ("sequence", ("path",)),
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
    "readlines": ("sequence", ("text",)),
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


def common_kind(kinds: list[Kind] | tuple[Kind, ...]) -> Kind:
    return kinds[0] if kinds and all(kind == kinds[0] for kind in kinds) else "value"


def item_kind(kind: Kind | None) -> Kind | None:
    if isinstance(kind, tuple):
        return kind[1][0] if kind[0] == "sequence" else common_kind(kind[1])
    return {"text": "text", "bytes": "value", "file": "text"}.get(kind)


def assignable_kind(kind: Kind | None) -> bool:
    if isinstance(kind, tuple):
        return all(assignable_kind(item) for item in kind[1])
    return kind in ASSIGNABLE_KINDS


def text_method_result(base: str, method: str) -> Kind:
    if method in {"split", "splitlines", "rsplit"}:
        return ("sequence", (base,))
    if method in {"partition", "rpartition"}:
        return ("tuple", (base, base, base))
    if method in {"decode", "encode"}:
        return "text" if method == "decode" else "bytes"
    if method.startswith("is") or method in {"count", "find", "index", "rfind", "rindex", "startswith", "endswith"}:
        return "value"
    return base


def is_known_read_only_python(source: str, *, cwd: str | None = None, isolated: bool = False) -> bool:
    try:
        tree = ast.parse(source, mode="exec")
    except (MemoryError, RecursionError, SyntaxError, TypeError, ValueError):
        return False
    return _ReadOnlyChecker().statements(tree.body) and (isolated or imports_are_trusted(cwd))


class _ReadOnlyChecker:
    def __init__(self) -> None:
        self.bindings: dict[str, Kind] = {
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
        elif isinstance(node, ast.For):
            result = (
                self.bind_target(node.target, item_kind(self.expression(node.iter)))
                and self.statements(node.body) and self.statements(node.orelse)
            )
        return result

    def suspicious_bare_literal(self, node: ast.expr) -> bool:
        if not isinstance(node, ast.Constant) or not isinstance(node.value, (str, bytes)):
            return False
        value = node.value.decode(errors="ignore") if isinstance(node.value, bytes) else node.value
        return bool(SUSPICIOUS_BARE_LITERAL_RE.search(value))

    def assignment(self, node: ast.Assign) -> bool:
        if len(node.targets) != 1:
            return False
        return self.bind_target(node.targets[0], self.expression(node.value))

    def bind_target(self, node: ast.expr, kind: Kind | None) -> bool:
        if not assignable_kind(kind):
            return False
        if isinstance(node, ast.Name) and node.id not in self.protected_names:
            self.bindings[node.id] = kind
            return True
        if isinstance(node, (ast.Tuple, ast.List)) and isinstance(kind, tuple) and kind[0] == "tuple":
            return len(node.elts) == len(kind[1]) and all(
                self.bind_target(target, value) for target, value in zip(node.elts, kind[1])
            )
        return False

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

    def expression(self, node: ast.expr) -> Kind | None:
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
            (ast.GeneratorExp, self.generator),
        )
        for node_type, handler in handlers:
            if isinstance(node, node_type):
                return handler(node)
        return None

    def constant(self, node: ast.Constant) -> str | None:
        if isinstance(node.value, (str, bytes)):
            return "text" if isinstance(node.value, str) else "bytes"
        return "value" if isinstance(node.value, SAFE_LITERAL_TYPES) else None

    def name(self, node: ast.Name) -> Kind | None:
        return self.bindings.get(node.id)

    def collection(self, node: ast.List | ast.Set | ast.Tuple) -> Kind | None:
        kinds = [self.expression(item) for item in node.elts]
        if None in kinds:
            return None
        if isinstance(node, ast.Tuple):
            return ("tuple", tuple(kinds))
        return ("sequence", (common_kind(kinds),))

    def dictionary(self, node: ast.Dict) -> str | None:
        return "value" if all(
            key is not None and self.expression(key) is not None and self.expression(value) is not None
            for key, value in zip(node.keys, node.values)
        ) else None

    def subscript(self, node: ast.Subscript) -> Kind | None:
        kind = self.expression(node.value)
        if kind is None or not self.slice(node.slice):
            return None
        return kind if isinstance(node.slice, ast.Slice) else item_kind(kind) or "value"

    def joined_string(self, node: ast.JoinedStr) -> str | None:
        return "text" if all(self.formatted_value(value) for value in node.values) else None

    def unary(self, node: ast.UnaryOp) -> str | None:
        return "value" if self.expression(node.operand) is not None else None

    def binary(self, node: ast.BinOp | ast.BoolOp) -> Kind | None:
        values = node.values if isinstance(node, ast.BoolOp) else (node.left, node.right)
        kinds = [self.expression(value) for value in values]
        if None in kinds:
            return None
        if isinstance(node.op, ast.Div) and "path" in kinds and all(kind in {"path", "text"} for kind in kinds):
            return "path"
        if isinstance(node.op, (ast.Add, ast.And, ast.Or)):
            return common_kind(kinds)
        return "value"

    def compare(self, node: ast.Compare) -> str | None:
        values = (node.left, *node.comparators)
        return "value" if all(self.expression(value) is not None for value in values) else None

    def conditional(self, node: ast.IfExp) -> Kind | None:
        kinds = [self.expression(value) for value in (node.test, node.body, node.orelse)]
        return common_kind(kinds[1:]) if None not in kinds else None

    def generator(self, node: ast.GeneratorExp) -> Kind | None:
        previous = self.bindings.copy()
        try:
            for generator in node.generators:
                kind = item_kind(self.expression(generator.iter))
                if generator.is_async or not self.bind_target(generator.target, kind):
                    return None
                if not all(self.expression(condition) is not None for condition in generator.ifs):
                    return None
            kind = self.expression(node.elt)
            return ("sequence", (kind,)) if assignable_kind(kind) else None
        finally:
            self.bindings = previous

    def call(self, node: ast.Call) -> Kind | None:
        if not self.arguments(node.args, node.keywords):
            return None
        if isinstance(node.func, ast.Name):
            return self.named_call(node)
        if isinstance(node.func, ast.Attribute):
            return self.attribute_call(node)
        return None

    def named_call(self, node: ast.Call) -> Kind | None:
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
        return self.builtin_call(func.id, node) if kind == "builtin" else None

    def builtin_call(self, name: str, node: ast.Call) -> Kind | None:
        if name in {"str", "repr", "bytes"}:
            return "bytes" if name == "bytes" else "text"
        if name == "range":
            return ("sequence", ("value",))
        if name == "zip":
            kinds = tuple(item_kind(self.expression(arg)) for arg in node.args)
            return ("sequence", (("tuple", kinds),)) if None not in kinds else None
        if name in {"enumerate", "list", "tuple", "set", "sorted"} and node.args:
            kind = item_kind(self.expression(node.args[0]))
            if kind is None:
                return None
            if name == "enumerate":
                kind = ("tuple", ("value", kind))
            return ("sequence", (kind,))
        return "value"

    def json_call(self, kind: str, node: ast.Call) -> str | None:
        if len(node.args) != 1 or node.keywords:
            return None
        source_kind = self.expression(node.args[0])
        if kind == "json_load":
            return "value" if source_kind == "file" else None
        return "value" if source_kind in {"text", "bytes", "value"} else None

    def attribute_call(self, node: ast.Call) -> Kind | None:
        if not isinstance(node.func, ast.Attribute):
            return None
        method = self.attribute(node.func)
        if method is None:
            return None
        if method in {"json_load", "json_loads"}:
            return self.json_call(method, node)
        if method.startswith("path_"):
            return self.method_result(method[5:], node)
        base, _, name = method.partition("_")
        if base in {"text", "bytes"}:
            return text_method_result(base, name)
        return FILE_METHODS.get(name) if base == "file" else None

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

    def method_result(self, method: str, node: ast.Call) -> Kind | None:
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
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return True
        if not isinstance(node, ast.FormattedValue) or self.expression(node.value) is None:
            return False
        return node.format_spec is None or self.expression(node.format_spec) is not None

    def _optional_expression(self, node: ast.expr | None) -> bool:
        return node is None or self.expression(node) is not None
