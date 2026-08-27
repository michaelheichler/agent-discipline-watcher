"""Resolves the embedding artifacts for the running machine, because the platform decides the build and a wrong one downloads a gigabyte that cannot load."""
from __future__ import annotations

import platform
from typing import NamedTuple


class Artifact(NamedTuple):
    name: str
    url: str
    sha256: str
    size: int


class ArchiveRuntime(NamedTuple):
    server: str
    archive: Artifact


class PythonRuntime(NamedTuple):
    requirements: tuple[str, ...]


class ModelPlatform(NamedTuple):
    key: str
    backend: str
    weights: tuple[Artifact, ...]
    runtime: ArchiveRuntime | PythonRuntime


DARWIN_ARM64 = "darwin-arm64"
LINUX_X86_64 = "linux-x86_64"
MLX_REPOSITORY = "mlx-community/LFM2.5-Embedding-350M-bf16"
MLX_REVISION = "14f29539bf823aec87252f92d69c9f1af9fdcbfd"
GGUF_REPOSITORY = "LiquidAI/LFM2.5-Embedding-350M-GGUF"
GGUF_REVISION = "a80de9c5b941d429104f0038292a0ef5a860e486"
GGUF_QUANTIZATION = "LFM2.5-Embedding-350M-Q8_0.gguf"
LLAMA_BUILD = "b10645"
LLAMA_ARCHIVE = f"llama-{LLAMA_BUILD}-bin-ubuntu-x64.tar.gz"
HUGGINGFACE_HOST = "https://huggingface.co"
LLAMA_RELEASE_HOST = "https://github.com/ggml-org/llama.cpp/releases/download"
# WHY: mlx ships no server binary, and transformers supplies only the tokenizer, so no torch is pulled.
MLX_REQUIREMENTS = ("mlx==0.32.2", "transformers==5.16.1")
SYSTEM_ALIASES = {"darwin": "darwin", "linux": "linux"}
MACHINE_ALIASES = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64", "amd64": "x86_64"}


def _huggingface_url(repository: str, revision: str, name: str) -> str:
    return f"{HUGGINGFACE_HOST}/{repository}/resolve/{revision}/{name}"


def _mlx_artifact(name: str, digest: str, size: int) -> Artifact:
    return Artifact(name, _huggingface_url(MLX_REPOSITORY, MLX_REVISION, name), digest, size)


MLX_WEIGHTS = (
    _mlx_artifact("config.json", "52e0f7e82a9161efca5dc02f5bbaf6bfe1f05d0bf5d81c1f5ed84aaf43dd5c58", 1546),
    _mlx_artifact("config_sentence_transformers.json", "a6089803863955ce7b31274bd02ad3a5ddbabc061dfca7ba88460514b91399b0", 555),
    _mlx_artifact("lfm2_bidirectional.py", "f8d1ca84cab891c78961a3c1e4fc8a76be33a7e47fd7a415e6553b8b8f702684", 10046),
    _mlx_artifact("model.safetensors", "bcd50fd7ea9a91744b56542f138414f0fecc42b57481e4bd262e50b55ed080ca", 708984408),
    _mlx_artifact("special_tokens_map.json", "742aefe2b7dec496e8caffdba03a75d0c1a9925d53bd3f3e0d388c96b591b6f4", 434),
    _mlx_artifact("tokenizer.json", "eb89449ddea8caaff6bcefc4993f30da173f3f1c6f30ad96bc964863f692f1cf", 4733275),
    _mlx_artifact("tokenizer_config.json", "7787607af2d3ed1afe861f2c5da946f63b1ff7ee39460bfe847801ae612069af", 92067),
)
GGUF_WEIGHTS = (
    Artifact(
        GGUF_QUANTIZATION,
        _huggingface_url(GGUF_REPOSITORY, GGUF_REVISION, GGUF_QUANTIZATION),
        "6ec5f8e8750dbc8a0e40c431fd1b7b07a13688136b2244c5a1364b54d9032599",
        379216640,
    ),
)
LLAMA_RUNTIME = ArchiveRuntime(
    f"llama-{LLAMA_BUILD}/llama-server",
    Artifact(
        LLAMA_ARCHIVE,
        f"{LLAMA_RELEASE_HOST}/{LLAMA_BUILD}/{LLAMA_ARCHIVE}",
        "4b6489224d22500348c6f7a01821a91f55b3d6e1756ee255e4ef99b1f35e4dd8",
        16307614,
    ),
)
PLATFORMS: dict[str, ModelPlatform] = {
    DARWIN_ARM64: ModelPlatform(DARWIN_ARM64, "mlx", MLX_WEIGHTS, PythonRuntime(MLX_REQUIREMENTS)),
    LINUX_X86_64: ModelPlatform(LINUX_X86_64, "gguf", GGUF_WEIGHTS, LLAMA_RUNTIME),
}


def platform_key(system: str, machine: str) -> str:
    """Names both halves in the error because a machine that resolves nothing needs to say what it is."""
    normalized_system = SYSTEM_ALIASES.get(system.strip().lower())
    normalized_machine = MACHINE_ALIASES.get(machine.strip().lower())
    key = f"{normalized_system}-{normalized_machine}"
    if normalized_system is None or normalized_machine is None or key not in PLATFORMS:
        raise ValueError(
            f"no embedding build for system {system!r} on machine {machine!r}, "
            f"supported platforms are {tuple(PLATFORMS)!r}"
        )
    return key


def resolve(system: str, machine: str) -> ModelPlatform:
    return PLATFORMS[platform_key(system, machine)]


def current_platform() -> ModelPlatform:
    return resolve(platform.system(), platform.machine())
