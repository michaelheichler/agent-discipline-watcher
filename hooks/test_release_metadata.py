import re
from pathlib import Path

from lib import update_release


def test_repository_release_metadata_passes_the_installed_updater_contract():
    root = Path(__file__).resolve().parents[1]
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    release = re.search(r"^## (\d+\.\d+\.\d+)\b", changelog, re.MULTILINE)
    assert release is not None
    contents = {
        name: (root / name).read_bytes()
        for name in ("README.md", ".claude-plugin/plugin.json")
    }
    update_release._validate_release_files(contents, f"v{release.group(1)}")
