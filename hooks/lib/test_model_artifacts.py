from __future__ import annotations

import re

import pytest

from lib import model_artifacts

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("Darwin", "arm64", model_artifacts.DARWIN_ARM64),
        ("darwin", "ARM64", model_artifacts.DARWIN_ARM64),
        ("Linux", "x86_64", model_artifacts.LINUX_X86_64),
        ("Linux", "amd64", model_artifacts.LINUX_X86_64),
    ],
)
def test_a_supported_machine_resolves_to_its_own_build(system, machine, expected) -> None:
    assert model_artifacts.platform_key(system, machine) == expected


@pytest.mark.parametrize(
    ("system", "machine"),
    [("Windows", "x86_64"), ("Linux", "aarch64"), ("Darwin", "x86_64"), ("", "")],
)
def test_an_unsupported_machine_names_itself_rather_than_guessing(system, machine) -> None:
    with pytest.raises(ValueError) as raised:
        model_artifacts.platform_key(system, machine)

    assert repr(system) in str(raised.value)
    assert repr(machine) in str(raised.value)


def test_the_mac_takes_mlx_and_the_x86_box_takes_gguf() -> None:
    assert model_artifacts.resolve("Darwin", "arm64").backend == "mlx"
    assert model_artifacts.resolve("Linux", "x86_64").backend == "gguf"


def test_every_artifact_carries_a_digest_a_size_and_a_pinned_revision() -> None:
    for entry in model_artifacts.PLATFORMS.values():
        runtime = entry.runtime
        archives = (runtime.archive,) if isinstance(runtime, model_artifacts.ArchiveRuntime) else ()
        for artifact in entry.weights + archives:
            assert SHA256_RE.match(artifact.sha256), artifact.name
            assert artifact.size > 0, artifact.name
            assert artifact.url.startswith("https://"), artifact.name
            assert "/main/" not in artifact.url, artifact.name


def test_the_mac_runtime_pins_every_requirement_it_names() -> None:
    runtime = model_artifacts.resolve("Darwin", "arm64").runtime

    assert isinstance(runtime, model_artifacts.PythonRuntime)
    assert all("==" in requirement for requirement in runtime.requirements)


def test_the_current_machine_resolves_without_reaching_the_network() -> None:
    assert model_artifacts.current_platform() in model_artifacts.PLATFORMS.values()
