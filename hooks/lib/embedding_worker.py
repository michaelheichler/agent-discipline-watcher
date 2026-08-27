"""Runs inside the runtime venv rather than the watcher's own interpreter, because mlx is a Mac wheel the hook process must never import."""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# pylint: disable=import-error
import mlx.core as mx  # WHY: lives in the runtime venv, never in the interpreter that runs the hooks.
from transformers import AutoTokenizer

MODULE_NAME = "lfm2_bidirectional"
MAX_LENGTH = 8192
MAX_BATCH = 32
HEALTH_PATH = "/health"
EMBEDDINGS_PATH = "/v1/embeddings"
NOT_FOUND = {"error": "not found"}
_LOCK = threading.Lock()


def _module(directory: Path):
    """Loaded from the model directory because the architecture ships with its weights and is pinned by the same sha256."""
    spec = importlib.util.spec_from_file_location(MODULE_NAME, directory / f"{MODULE_NAME}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _weights(directory: Path, module) -> dict:
    weights: dict = {}
    for path in sorted(directory.glob("model*.safetensors")):
        weights.update(mx.load(str(path)))
    return module.sanitize(weights)


def load(directory: Path):
    module = _module(directory)
    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    model = module.EmbeddingModel(module.ModelArgs.from_dict(config))
    model.load_weights(list(_weights(directory, module).items()))
    mx.eval(model.parameters())
    model.eval()
    return model, AutoTokenizer.from_pretrained(str(directory))


def _encode(model, tokenizer, texts: list[str]) -> list[list[float]]:
    with _LOCK:
        encoded = tokenizer(texts, padding=True, truncation=True, max_length=MAX_LENGTH, return_tensors="np")
        vectors = model.encode(mx.array(encoded["input_ids"]), mx.array(encoded["attention_mask"]), normalize=True)
        mx.eval(vectors)
        return vectors.tolist()


def embed(model, tokenizer, texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), MAX_BATCH):
        vectors.extend(_encode(model, tokenizer, texts[start : start + MAX_BATCH]))
    return vectors


def _texts(body: dict) -> list[str]:
    given = body.get("input")
    if isinstance(given, str):
        return [given]
    if isinstance(given, list) and all(isinstance(item, str) for item in given):
        return given
    raise ValueError(f"input must be a string or a list of strings, got {given!r}")


class _Handler(BaseHTTPRequestHandler):
    model = None
    tokenizer = None
    model_id = ""

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != HEALTH_PATH:
            self._send(404, NOT_FOUND)
            return
        self._send(200, {"status": "ok"})

    def _embeddings(self) -> dict:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8"))
        vectors = embed(type(self).model, type(self).tokenizer, _texts(body))
        rows = [{"object": "embedding", "index": index, "embedding": vector} for index, vector in enumerate(vectors)]
        return {"object": "list", "data": rows, "model": type(self).model_id}

    def do_POST(self) -> None:
        if self.path != EMBEDDINGS_PATH:
            self._send(404, NOT_FOUND)
            return
        try:
            self._send(200, self._embeddings())
        except (ValueError, KeyError, TypeError) as error:
            self._send(400, {"error": str(error)})

    def log_message(self, format: str, *args: object) -> None:  # pylint: disable=redefined-builtin
        return


def serve(directory: Path, port: int) -> None:
    _Handler.model, _Handler.tokenizer = load(directory)
    _Handler.model_id = directory.name
    ThreadingHTTPServer(("127.0.0.1", port), _Handler).serve_forever()


if __name__ == "__main__":
    serve(Path(sys.argv[1]), int(sys.argv[2]))
