from __future__ import annotations

import ast
import re

from .python_imports import imports_are_trusted
from .python_safe_modules import (
    BYTES_METHODS, FILE_METHODS, IMPORTABLE, ITEMS, JSON_ELEMENT_METHODS, JSON_METHODS, OBJECT_KINDS,
    PATH_CLASS_METHODS, PATH_METHODS, TEXT_METHODS, Kind, callable_result, from_import_kind, import_binding,
    member_kind, text_method_result,
)

READ_ONLY_OPEN_MODE_CHARS = frozenset("rbtU")
OPEN_KEYWORDS = frozenset({"buffering", "encoding", "errors", "newline", "closefd"})
SAFE_IMPORTS = {"json": "json_module", "sys": "sys_module"}
SYS_ATTRIBUTES: dict[str, Kind] = {
    "stdin": "file", "argv": ("sequence", ("text",)), "executable": "text", "maxsize": "value",
    "platform": "text", "version": "text", "version_info": "value",
}
JSON_FUNCTIONS = frozenset({"dumps", "load", "loads"})
DUMPS_KEYWORDS = frozenset({"allow_nan", "ensure_ascii", "indent", "separators", "skipkeys", "sort_keys"})
PATH_CLASSES = frozenset({"Path", "PurePath"})
SORT_HELPERS = frozenset({"max", "min", "sorted"})
CONTAINER_LITERALS = (ast.Dict, ast.DictComp, ast.List, ast.ListComp)
UNASSIGNED_HINT = ", which is never assigned in this payload. Define it or inline the value"
SAFE_BUILTINS = frozenset({
    "abs", "all", "any", "bool", "bytes", "dict", "enumerate", "float", "int", "isinstance", "iter", "len", "list", "max",
    "min", "next", "print", "range", "repr", "round", "set", "sorted", "str", "sum", "tuple", "type", "zip",
})
SAFE_EXCEPTIONS = frozenset({
    "ArithmeticError", "AttributeError", "Exception", "FileNotFoundError", "IndexError", "KeyError",
    "LookupError", "OSError", "StopIteration", "TypeError", "UnicodeDecodeError", "ValueError", "ZeroDivisionError",
})
JSON_ERROR = "JSONDecodeError"
FIXED_BUILTIN_KINDS: dict[str, Kind] = {"str": "text", "repr": "text", "bytes": "bytes", "range": ("sequence", ("value",))}
SAFE_LITERAL_TYPES = (str, bytes, int, float, complex, bool, type(None))
ASSIGNABLE_KINDS = frozenset({"bytes", "file", "json", "path", "text", "value"}) | OBJECT_KINDS

SUSPICIOUS_BARE_LITERAL_RE = re.compile(r"(?:\b(?:write|exec|eval)\s*\(|__)")

Comprehension = ast.GeneratorExp | ast.ListComp | ast.SetComp | ast.DictComp


def common_kind(kinds: list[Kind] | tuple[Kind, ...]) -> Kind:
    return kinds[0] if kinds and all(kind == kinds[0] for kind in kinds) else "value"


def item_kind(kind: Kind | None) -> Kind | None:
    if isinstance(kind, tuple):
        return kind[1][0] if kind[0] == "sequence" else common_kind(kind[1])
    return {"text": "text", "bytes": "value", "file": "text", "json": "json", **ITEMS}.get(kind)


def assignable_kind(kind: Kind | None) -> bool:
    if isinstance(kind, tuple):
        return all(assignable_kind(item) for item in kind[1])
    return kind in ASSIGNABLE_KINDS


def is_known_read_only_python(source: str, *, cwd: str | None = None, isolated: bool = False) -> bool:
    return not python_rejection(source, cwd=cwd, isolated=isolated)


def python_rejection(source: str, *, cwd: str | None = None, isolated: bool = False) -> str:
    try:
        tree = ast.parse(source, mode="exec")
    except (MemoryError, RecursionError, SyntaxError, TypeError, ValueError):
        return "code that does not parse"
    checker = _ReadOnlyChecker()
    if not checker.statements(tree.body):
        return describe_rejection(checker) if checker.rejected else "an unsupported construct"
    if not (isolated or imports_are_trusted(cwd)):
        return "a project module that shadows a standard library import"
    return ""


def describe_node(node: ast.AST) -> str:
    try:
        text = " ".join(ast.unparse(node).split())
    except (RecursionError, ValueError):
        text = ""
    return f"{type(node).__name__} \"{text[:80]}\" on line {getattr(node, 'lineno', '?')}"


def describe_rejection(checker: _ExpressionKinds) -> str:
    node = checker.rejected
    unassigned = isinstance(node, ast.Name) and node.id not in checker.bindings
    return describe_node(node) + (UNASSIGNED_HINT if unassigned else "")


class _ExpressionKinds:
    def __init__(self) -> None:
        self.bindings: dict[str, Kind] = {
            name: "builtin" for name in SAFE_BUILTINS
        }
        self.bindings["open"] = "open"
        module_roots = {name.partition(".")[0] for name in IMPORTABLE}
        self.protected_names = set(self.bindings) | set(SAFE_IMPORTS) | module_roots | PATH_CLASSES
        self.containers: set[str] = set()
        self.rejected: ast.AST | None = None

    def noted(self, node: ast.AST, result: Kind | bool | None) -> Kind | bool | None:
        if not result and self.rejected is None:
            self.rejected = node
        return result

    def bind_target(self, node: ast.expr, kind: Kind | None) -> bool:
        if not assignable_kind(kind):
            return False
        if isinstance(node, ast.Name) and node.id not in self.protected_names:
            self.bindings[node.id] = kind
            self.containers.discard(node.id)
            return True
        if isinstance(node, (ast.Tuple, ast.List)) and isinstance(kind, tuple) and kind[0] == "tuple":
            return len(node.elts) == len(kind[1]) and all(
                self.bind_target(target, value) for target, value in zip(node.elts, kind[1])
            )
        return False

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
            ((ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp), self.generator),
        )
        for node_type, handler in handlers:
            if isinstance(node, node_type):
                return self.noted(node, handler(node))
        return self.noted(node, None)

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
        return "dict" if all(
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

    def generator(self, node: Comprehension) -> Kind | None:
        previous = self.bindings.copy()
        try:
            return self.comprehension_result(node) if self.bind_comprehension(node.generators) else None
        finally:
            self.bindings = previous

    def bind_comprehension(self, generators: list[ast.comprehension]) -> bool:
        for generator in generators:
            kind = item_kind(self.expression(generator.iter))
            if generator.is_async or not self.bind_target(generator.target, kind):
                return False
            if not all(self.expression(condition) is not None for condition in generator.ifs):
                return False
        return True

    def comprehension_result(self, node: Comprehension) -> Kind | None:
        if isinstance(node, ast.DictComp):
            kinds = (self.expression(node.key), self.expression(node.value))
            return "dict" if all(assignable_kind(kind) for kind in kinds) else None
        kind = self.expression(node.elt)
        return ("sequence", (kind,)) if assignable_kind(kind) else None

    def call(self, node: ast.Call) -> Kind | None:
        keywords = [keyword for keyword in node.keywords if not self.sort_key(node, keyword)]
        if not self.arguments(node.args, keywords):
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
        if kind in {"json_dumps", "json_load", "json_loads"}:
            return self.json_call(kind, node)
        if kind == "builtin":
            return self.builtin_call(func.id, node)
        return callable_result(kind, self.item_kinds(node.args))

    def sort_key(self, node: ast.Call, keyword: ast.keyword) -> bool:
        func = node.func
        if keyword.arg != "key" or not isinstance(keyword.value, ast.Lambda) or not node.args:
            return False
        if not isinstance(func, ast.Name) or func.id not in SORT_HELPERS or self.bindings.get(func.id) != "builtin":
            return False
        return self.lambda_body(keyword.value, item_kind(self.expression(node.args[0])) or "value")

    def lambda_body(self, node: ast.Lambda, kind: Kind) -> bool:
        args = node.args
        if len(args.args) != 1 or any((args.posonlyargs, args.kwonlyargs, args.vararg, args.kwarg, args.defaults)):
            return False
        previous, containers = self.bindings.copy(), self.containers.copy()
        try:
            return self.bind_target(ast.Name(args.args[0].arg), kind) and self.expression(node.body) is not None
        finally:
            self.bindings, self.containers = previous, containers

    def item_kinds(self, args: list[ast.expr]) -> list[Kind | None]:
        return [item_kind(self.expression(arg)) for arg in args]

    def builtin_call(self, name: str, node: ast.Call) -> Kind | None:
        if name in FIXED_BUILTIN_KINDS:
            return FIXED_BUILTIN_KINDS[name]
        if name in {"iter", "next", "type"}:
            return self.lookup_call(name, node)
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

    def lookup_call(self, name: str, node: ast.Call) -> Kind | None:
        """Because type with three arguments builds a class, only the one-argument type lookup passes."""
        if name == "type":
            return "value" if len(node.args) == 1 and not node.keywords else None
        if name == "iter":
            # Because iter with a sentinel calls its first argument.
            return self.expression(node.args[0]) if len(node.args) == 1 and not node.keywords else None
        kinds = self.item_kinds(node.args[:1])
        if len(node.args) == 1 and kinds:
            return kinds[0]
        return "value" if len(node.args) == 2 else None

    def json_call(self, kind: str, node: ast.Call) -> str | None:
        if kind == "json_dumps":
            plain = len(node.args) == 1 and all(keyword.arg in DUMPS_KEYWORDS for keyword in node.keywords)
            return "text" if plain else None
        if len(node.args) != 1 or node.keywords:
            return None
        source_kind = self.expression(node.args[0])
        if kind == "json_load":
            return "json" if source_kind == "file" else None
        return "json" if source_kind in {"text", "bytes", "value"} else None

    def attribute_call(self, node: ast.Call) -> Kind | None:
        method = self.attribute(node.func) if isinstance(node.func, ast.Attribute) else None
        if not isinstance(method, str):
            return None
        if method in {"json_dumps", "json_load", "json_loads"}:
            return self.json_call(method, node)
        if method.startswith(("fn:", "ns:", "method:")):
            return callable_result(method, self.item_kinds(node.args))
        if method.startswith("path_"):
            return self.method_result(method[5:], node)
        base, _, name = method.partition("_")
        if base in {"text", "bytes"} or (base == "json" and name not in JSON_METHODS):
            return text_method_result("text" if base == "json" else base, name)
        return {"json": JSON_METHODS, "file": FILE_METHODS}.get(base, {}).get(name)

    def attribute(self, node: ast.Attribute) -> Kind | None:
        base = self.expression(node.value)
        if base == "json_module" and node.attr in JSON_FUNCTIONS:
            return f"json_{node.attr}"
        if base == "sys_module":
            return SYS_ATTRIBUTES.get(node.attr)
        if base == "path_ctor" and node.attr in PATH_CLASS_METHODS:
            return f"path_{node.attr}"
        member = member_kind(base, node.attr)
        if member is not None:
            return member
        methods = {
            "path": PATH_METHODS,
            "file": FILE_METHODS,
            "json": JSON_ELEMENT_METHODS,
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
        """Refuses open as an argument value, because reduce(open, [path, "w"]) would call it with a write mode."""
        values = [*args, *(keyword.value for keyword in keywords)]
        return all(keyword.arg is not None for keyword in keywords) and all(self.argument(value) for value in values)

    def argument(self, node: ast.expr) -> bool:
        kind = self.expression(node)
        return kind is not None and self.noted(node, kind != "open") is True

    def read_open(self, args: list[ast.expr], keywords: list[ast.keyword]) -> bool:
        if not args or any(isinstance(arg, ast.Starred) for arg in args) or not self.expression(args[0]):
            return False
        if len(args) > 2 or not all(self.open_keyword(keyword) for keyword in keywords):
            return False
        modes = [*args[1:2], *(keyword.value for keyword in keywords if keyword.arg == "mode")]
        if len(modes) > 1:
            return False
        if not modes:
            return True
        mode = modes[0]
        return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and set(mode.value) <= READ_ONLY_OPEN_MODE_CHARS

    def open_keyword(self, keyword: ast.keyword) -> bool:
        if keyword.arg == "mode":
            return True
        return keyword.arg in OPEN_KEYWORDS and self.expression(keyword.value) is not None

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


class _ReadOnlyChecker(_ExpressionKinds):
    def statements(self, nodes: list[ast.stmt]) -> bool:
        return all(self.statement(node) for node in nodes)

    def statement(self, node: ast.stmt) -> bool:
        handlers = (
            (ast.Expr, self.expression_statement),
            (ast.Assert, self.assert_statement),
            (ast.Import, self.imports),
            (ast.ImportFrom, self.import_from),
            (ast.Pass, self.pass_statement),
            (ast.Continue, self.pass_statement),
            (ast.Break, self.pass_statement),
            (ast.Try, self.try_statement),
            (ast.Assign, self.assignment),
            (ast.AugAssign, self.augmented_assignment),
            (ast.If, self.if_statement),
            (ast.With, self.with_statement),
            (ast.For, self.for_statement),
        )
        for node_type, handler in handlers:
            if isinstance(node, node_type):
                return bool(self.noted(node, handler(node)))
        return bool(self.noted(node, False))

    def expression_statement(self, node: ast.Expr) -> bool:
        return self.expression(node.value) is not None and not self.suspicious_bare_literal(node.value)

    def assert_statement(self, node: ast.Assert) -> bool:
        return self.expression(node.test) is not None and (node.msg is None or self.expression(node.msg) is not None)

    def pass_statement(self, _node: ast.Pass) -> bool:
        return True

    def try_statement(self, node: ast.Try) -> bool:
        return (
            self.statements(node.body) and all(self.handler(handler) for handler in node.handlers)
            and self.statements(node.orelse) and self.statements(node.finalbody)
        )

    def handler(self, node: ast.ExceptHandler) -> bool:
        """Because the clause evaluates its type at run time, only builtin exceptions the payload never rebinds pass."""
        if node.type is not None and not self.exception_type(node.type):
            return False
        if node.name is not None:
            if node.name in self.protected_names:
                return False
            self.bindings[node.name] = "value"
        return self.statements(node.body)

    def exception_type(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Tuple):
            return all(self.exception_type(item) for item in node.elts)
        if isinstance(node, ast.Attribute):
            return node.attr == JSON_ERROR and self.expression(node.value) == "json_module"
        return isinstance(node, ast.Name) and node.id in SAFE_EXCEPTIONS and node.id not in self.bindings

    def if_statement(self, node: ast.If) -> bool:
        return self.expression(node.test) is not None and self.statements(node.body) and self.statements(node.orelse)

    def for_statement(self, node: ast.For) -> bool:
        return (
            self.bind_target(node.target, item_kind(self.expression(node.iter)))
            and self.statements(node.body) and self.statements(node.orelse)
        )

    def suspicious_bare_literal(self, node: ast.expr) -> bool:
        if not isinstance(node, ast.Constant) or not isinstance(node.value, (str, bytes)):
            return False
        value = node.value.decode(errors="ignore") if isinstance(node.value, bytes) else node.value
        return bool(SUSPICIOUS_BARE_LITERAL_RE.search(value))

    def assignment(self, node: ast.Assign) -> bool:
        if len(node.targets) != 1:
            return False
        target = node.targets[0]
        if isinstance(target, ast.Subscript):
            return self.container_item(target) and self.expression(node.value) is not None
        bound = self.bind_target(target, self.expression(node.value))
        if bound and isinstance(target, ast.Name) and isinstance(node.value, CONTAINER_LITERALS):
            self.containers.add(target.id)
        return bound

    def augmented_assignment(self, node: ast.AugAssign) -> bool:
        if isinstance(node.target, ast.Subscript):
            return self.container_item(node.target) and self.expression(node.value) is not None
        if not isinstance(node.target, ast.Name) or node.target.id not in self.bindings:
            return False
        current = ast.BinOp(ast.Name(node.target.id, ast.Load()), node.op, node.value)
        return self.bind_target(node.target, self.expression(ast.copy_location(current, node)))

    def container_item(self, node: ast.Subscript) -> bool:
        """Only a dict or list this payload built, because an item store elsewhere can reach an object that writes."""
        owned = isinstance(node.value, ast.Name) and node.value.id in self.containers
        return owned and self.slice(node.slice)

    def imports(self, node: ast.Import) -> bool:
        bindings = [self.import_name(alias) for alias in node.names]
        if None in bindings:
            return False
        for name, kind in (binding for binding in bindings if binding is not None):
            self.bindings[name] = kind
            self.protected_names.add(name)
        return True

    def import_name(self, alias: ast.alias) -> tuple[str, Kind] | None:
        if alias.asname is not None:
            return None
        if alias.name in SAFE_IMPORTS:
            return alias.name, SAFE_IMPORTS[alias.name]
        return import_binding(alias.name)

    def import_from(self, node: ast.ImportFrom) -> bool:
        if node.level or node.module is None:
            return False
        kinds = [self.from_kind(node.module, alias) for alias in node.names]
        if None in kinds:
            return False
        for alias, kind in zip(node.names, kinds):
            self.bindings[alias.name] = kind
            self.protected_names.add(alias.name)
        return True

    def from_kind(self, module: str, alias: ast.alias) -> Kind | None:
        if alias.asname is not None:
            return None
        if module == "pathlib":
            return "path_ctor" if alias.name in PATH_CLASSES else None
        if module == "json":
            return f"json_{alias.name}" if alias.name in JSON_FUNCTIONS else None
        return from_import_kind(module, alias.name)

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
