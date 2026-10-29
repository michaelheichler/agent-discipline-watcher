"""Run in a real repo with tests denied, because each read-only route once blocked and each write beside it must keep blocking."""
from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from lib import protected, tests_policy
from test_tests_policy_gate import blocked_by, project, shell
from testing import make_repo, run_git as git

TRACKED = (
    "src/a.py", "tests/test_x.py", "web/cart.test.ts", "web/cart.spec.ts",
    "assets/a.png", "assets/b.png", ".agents/skills/x/SKILL.md", "notes.txt",
)
SOURCE_PATCH = "--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
TEST_PATCH = "--- a/tests/test_x.py\n+++ b/tests/test_x.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
WRITE_RULE = "inline_interpreter_write"


@pytest.fixture(autouse=True)
def _no_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(protected.AUTH_ENV, raising=False)
    monkeypatch.delenv("OMPCODE", raising=False)


def write_tar(path: Path, members: tuple[str, ...], link: str = "") -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name in members:
            info = tarfile.TarInfo(name)
            info.size = 6
            archive.addfile(info, io.BytesIO(b"x = 1\n"))
        if link:
            info = tarfile.TarInfo(link)
            info.type = tarfile.SYMTYPE
            info.linkname = "tests/test_x.py"
            archive.addfile(info)


def write_zip(path: Path, members: tuple[str, ...]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name in members:
            archive.writestr(name, "x = 1\n")


def denied_repo(tmp_path: Path) -> Path:
    repo = project(make_repo(tmp_path), tests="deny")
    for name in TRACKED:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", "--", *TRACKED)
    git(repo, "commit", "-qm", "start")
    (repo / "scratch").mkdir()
    write_tar(repo / "plain.tgz", ("pkg/docs/readme.md", "pkg/src/b.py"))
    write_tar(repo / "tested.tgz", ("pkg/tests/test_y.py",))
    write_tar(repo / "linked.tgz", ("pkg/a.md",), link="pkg/link")
    write_tar(repo / "named.tgz", ("package/dist/a.js", "package/dist/b.js", "package/src/aabb.test.ts"))
    (repo / "members.txt").write_text("package/src/aabb.test.ts\n", encoding="utf-8")
    write_tar(repo / "mixed.tgz", ("tests/x.py", "docs/a.md", "ok.txt"))
    write_tar(repo / "flat.tgz", ("x.py", "y.py"))
    write_zip(repo / "plain.zip", ("docs/a.md",))
    write_zip(repo / "tested.zip", ("tests/test_z.py",))
    (repo / "source.patch").write_text(SOURCE_PATCH, encoding="utf-8")
    (repo / "test.patch").write_text(TEST_PATCH, encoding="utf-8")
    (repo / "data.json").write_text('{"a": 1}', encoding="utf-8")
    return repo


READ_ONLY_COMMANDS = [
    pytest.param("sed -n 1,200p web/cart.test.ts", id="sed-print-test-ts"),
    pytest.param("sed -n 1,200p web/cart.spec.ts", id="sed-print-spec-ts"),
    pytest.param("""sed -n '1,65p' ".agents/skills/$file/SKILL.md\"""", id="sed-print-expanded-operand"),
    pytest.param("git restore --staged assets/*.png", id="restore-staged-glob"),
    pytest.param("tar -xOf plain.tgz", id="tar-to-stdout-cluster"),
    pytest.param("tar -xzf plain.tgz -C scratch --strip-components=1", id="tar-plain-members-stripped"),
    pytest.param("tar xz -C scratch < plain.tgz", id="tar-old-style-stdin"),
    pytest.param("tar -xzf named.tgz -C scratch package/dist/a.js package/dist/b.js", id="tar-named-plain-members"),
    pytest.param("tar -xzf mixed.tgz ./ok.txt", id="tar-named-member-with-leading-dot-slash"),
    pytest.param("tar -xzf mixed.tgz docs/", id="tar-named-folder-with-trailing-slash"),
    pytest.param("find src -name '*.js' -exec node --check {} \\;", id="find-exec-node-check"),
    pytest.param("find src -name '*.sh' -exec bash -n {} \\;", id="find-exec-bash-syntax-check"),
    pytest.param("unzip -lq plain.zip", id="unzip-list-cluster"),
    pytest.param("unzip plain.zip -d scratch", id="unzip-plain-members"),
    pytest.param("git apply source.patch", id="git-apply-source"),
    pytest.param("git apply < source.patch", id="git-apply-stdin"),
    pytest.param("patch -o scratch/a.py src/a.py source.patch", id="patch-output-elsewhere"),
    pytest.param("python3 -c 'for n in range(3):\n    if n == 1:\n        continue\n    print(n)'", id="python-continue"),
    pytest.param("python3 -c 'for n in range(3):\n    break'", id="python-break"),
    pytest.param(
        "python3 -c 'try:\n    print(int(\"x\"))\nexcept Exception as error:\n    print(error)'", id="python-try-except",
    ),
    pytest.param(
        "python3 -c 'import json\ntry:\n    json.loads(\"{\")\nexcept json.JSONDecodeError:\n    print(0)'",
        id="python-except-json-error",
    ),
    pytest.param("python3 -c 'print(next((n for n in [1, 2] if n > 1), None))'", id="python-next"),
    pytest.param("python3 -c 'print(type(1), isinstance(1, int), abs(-1), round(1.5))'", id="python-lookups"),
    pytest.param("python3 -c 'import yaml; print(yaml.__version__)'", id="python-yaml-version"),
    pytest.param("""python3 -c 'import yaml; print(yaml.safe_load(open("a.yml")))'""", id="python-yaml-safe-load"),
    pytest.param("""node -e 'const d=require("./data.json"); console.log(JSON.stringify(d))'""", id="node-json-require"),
    pytest.param("python3 -c 'print(1)' > scratch/out.txt", id="python-into-text-file"),
]


@pytest.mark.parametrize("command", READ_ONLY_COMMANDS)
def test_deny_passes_a_command_that_only_reads(tmp_path: Path, command: str) -> None:
    assert shell(denied_repo(tmp_path), command).get("decision") != "block"


WRITING_COMMANDS = [
    pytest.param("sed -i 's/x/y/' web/cart.test.ts", tests_policy.RULE, id="sed-in-place-test"),
    pytest.param("sed -n 'w tests/x.py' notes.txt", "dynamic_write_target", id="sed-w-command"),
    pytest.param('sed -n "1,${n}p" notes.txt', "dynamic_write_target", id="sed-expanded-script"),
    pytest.param("ls | xargs sed -n 1p", "dynamic_write_target", id="xargs-sed"),
    pytest.param("git restore --staged --worktree tests/test_x.py", tests_policy.RULE, id="restore-worktree-test"),
    pytest.param("git restore --source=HEAD~1 --staged 'tests/*.py'", tests_policy.RULE, id="restore-source-test-glob"),
    pytest.param("tar -xzf tested.tgz -C scratch", tests_policy.RULE, id="tar-test-member"),
    pytest.param("tar -xzf linked.tgz -C scratch", tests_policy.RULE, id="tar-symlink-member"),
    pytest.param("curl -sL https://example.test/a.tgz | tar xz", tests_policy.RULE, id="tar-from-pipe"),
    pytest.param("tar --to-command=cat -xzf plain.tgz", tests_policy.RULE, id="tar-to-command"),
    pytest.param("tar -xzf named.tgz -C scratch package/src/aabb.test.ts", tests_policy.RULE, id="tar-named-test-member"),
    pytest.param("tar -xzf named.tgz -C scratch package/src", tests_policy.RULE, id="tar-named-test-folder"),
    pytest.param("tar -xzf named.tgz -C scratch package", tests_policy.RULE, id="tar-named-top-folder"),
    pytest.param("tar -xzf named.tgz -C scratch 'package/s*'", tests_policy.RULE, id="tar-named-wildcard"),
    pytest.param("tar -xzf named.tgz -C scratch -T members.txt package/dist/a.js", tests_policy.RULE,
                 id="tar-member-list-file"),
    pytest.param("tar -xzf named.tgz -C scratch --files-from=members.txt package/dist/a.js", tests_policy.RULE,
                 id="tar-files-from"),
    pytest.param("tar -xzf mixed.tgz tests//x.py", tests_policy.RULE, id="tar-operand-empty-segment"),
    pytest.param("tar -xzf mixed.tgz tests/./x.py", tests_policy.RULE, id="tar-operand-dot-segment"),
    pytest.param("tar -xzf mixed.tgz tests/.", tests_policy.RULE, id="tar-operand-trailing-dot"),
    pytest.param("tar -xzf mixed.tgz tests/x.py/.", tests_policy.RULE, id="tar-operand-member-then-dot"),
    pytest.param("tar -xzf mixed.tgz .//tests/x.py", tests_policy.RULE, id="tar-operand-dot-then-empty-segment"),
    pytest.param("tar -xzf flat.tgz -C tests x.py -C scratch y.py", tests_policy.RULE, id="tar-second-short-directory"),
    pytest.param("tar -xzf flat.tgz --directory=tests x.py -C scratch y.py", tests_policy.RULE,
                 id="tar-long-then-short-directory"),
    pytest.param("find src -name '*.js' -exec node {} \\;", "dynamic_write_target", id="find-exec-node-runs"),
    pytest.param("find src -exec bash -c 'echo x > out.txt' \\;", "dynamic_write_target", id="find-exec-bash-c"),
    pytest.param("find web -name '*.ts' -exec sed -i 's/x/y/' {} \\;", "dynamic_write_target", id="find-exec-sed-in-place"),
    pytest.param("unzip tested.zip -d scratch", tests_policy.RULE, id="unzip-test-member"),
    pytest.param("git apply test.patch", tests_policy.RULE, id="git-apply-test"),
    pytest.param("patch -p1 < test.patch", tests_policy.RULE, id="patch-test"),
    pytest.param("patch -o tests/test_x.py src/a.py source.patch", tests_policy.RULE, id="patch-output-test"),
    pytest.param(
        """python3 -c 'import yaml; print(yaml.load(open("a.yml"), Loader=yaml.Loader))'""", WRITE_RULE,
        id="python-yaml-load",
    ),
    pytest.param("""python3 -c 'try:\n    open("x.txt", "w")\nexcept OSError:\n    pass'""", WRITE_RULE, id="python-try-open"),
    pytest.param("""python3 -c 'print(type("C", (), {}))'""", WRITE_RULE, id="python-type-builds-class"),
    pytest.param(
        """python3 -c 'try:\n    pass\nexcept open("x.txt", "w"):\n    pass'""", WRITE_RULE, id="python-except-calls-open",
    ),
    pytest.param(
        """python3 -c 'try:\n    print(1)\nexcept OSError:\n    open("x.txt", "w")'""", WRITE_RULE, id="python-handler-opens",
    ),
    pytest.param(
        "python3 -c 'Exception = OSError\ntry:\n    print(1)\nexcept Exception:\n    pass'", WRITE_RULE,
        id="python-rebound-exception",
    ),
    pytest.param(
        """node -e 'const d=require("./data.json"); require("fs").writeFileSync("a.txt", "x")'""", WRITE_RULE,
        id="node-fs-beside-json",
    ),
    pytest.param("""node -e 'console.log(require("./absent.json"))'""", WRITE_RULE, id="node-json-not-a-file"),
    pytest.param("python3 -c 'print(1)' > out.py", "opaque_source_write", id="python-into-source-file"),
]


@pytest.mark.parametrize(("command", "rule"), WRITING_COMMANDS)
def test_deny_blocks_a_command_that_may_write(tmp_path: Path, command: str, rule: str) -> None:
    assert blocked_by(shell(denied_repo(tmp_path), command), rule)


def test_a_project_yaml_module_makes_a_yaml_import_untrusted(tmp_path: Path) -> None:
    cwd = denied_repo(tmp_path)
    (cwd / "yaml.py").write_text("__version__ = 1\n", encoding="utf-8")
    assert shell(cwd, "python3 -c 'import yaml; print(yaml.__version__)'").get("decision") == "block"
