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
MAX_INPUTS = 8192
MAX_TEXT_CHARS = 16_384
MAX_BODY_BYTES = 1_048_576
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
    """Encode a bounded collection in fixed-size tokenizer batches."""
    if len(texts) > MAX_INPUTS:
        raise ValueError(f"input contains more than {MAX_INPUTS} texts")
    if any(not isinstance(text, str) for text in texts):
        raise ValueError("input must contain only strings")
    if any(len(text) > MAX_TEXT_CHARS for text in texts):
        raise ValueError(f"input text exceeds {MAX_TEXT_CHARS} characters")
    vectors: list[list[float]] = []
    for start in range(0, len(texts), MAX_BATCH):
        vectors.extend(_encode(model, tokenizer, texts[start : start + MAX_BATCH]))
    return vectors


def _texts(body: dict) -> list[str]:
    """Validate one request's input list before tokenization can consume it."""
    if not isinstance(body, dict):
        raise ValueError("request body must be a JSON object")
    given = body.get("input")
    if isinstance(given, str):
        texts = [given]
    elif isinstance(given, list) and all(isinstance(item, str) for item in given):
        texts = given
    else:
        raise ValueError("input must be a string or a list of strings")
    if len(texts) > MAX_BATCH:
        raise ValueError(f"input contains more than {MAX_BATCH} texts")
    if any(len(text) > MAX_TEXT_CHARS for text in texts):
        raise ValueError(f"input text exceeds {MAX_TEXT_CHARS} characters")
    return texts


class _PayloadTooLarge(ValueError):
    """Mark a request rejected before its body is read into memory."""


def _read_body(handler: BaseHTTPRequestHandler) -> bytes:
    """Read exactly one bounded HTTP request body from the Content-Length header."""
    header = handler.headers.get("Content-Length")
    if header is None:
        raise ValueError("Content-Length header is required")
    header = header.strip()
    if not header.isascii() or not header.isdigit():
        raise ValueError("Content-Length header must be a non-negative integer")
    try:
        length = int(header)
    except ValueError as error:
        raise ValueError("Content-Length header is invalid") from error
    if length > MAX_BODY_BYTES:
        raise _PayloadTooLarge(f"request body exceeds {MAX_BODY_BYTES} bytes")
    body = handler.rfile.read(length)
    if len(body) != length:
        raise ValueError("request body is truncated")
    return body


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
        """Parse and encode one bounded JSON request."""
        try:
            raw = _read_body(self)
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
            raise ValueError("request body must be valid UTF-8 JSON") from error
        if not isinstance(body, dict):
            raise ValueError("request body must be a JSON object")
        vectors = embed(type(self).model, type(self).tokenizer, _texts(body))
        rows = [
            {"object": "embedding", "index": index, "embedding": vector}
            for index, vector in enumerate(vectors)
        ]
        return {"object": "list", "data": rows, "model": type(self).model_id}

    def do_POST(self) -> None:
        if self.path != EMBEDDINGS_PATH:
            self._send(404, NOT_FOUND)
            return
        try:
            self._send(200, self._embeddings())
        except _PayloadTooLarge as error:
            self._send(413, {"error": str(error)})
        except (ValueError, KeyError, TypeError) as error:
            self._send(400, {"error": str(error)})

    def log_message(self, format: str, *args: object) -> None:  # pylint: disable=redefined-builtin
        return


def serve(directory: Path, port: int) -> None:
    """Load the model and bind the worker only to a valid loopback port."""
    if type(port) is not int or not 1 <= port <= 65_535:  # pylint: disable=unidiomatic-typecheck
        raise ValueError("port must be between 1 and 65535")
    _Handler.model, _Handler.tokenizer = load(directory)
    _Handler.model_id = directory.name
    ThreadingHTTPServer(("127.0.0.1", port), _Handler).serve_forever()


if __name__ == "__main__":
    serve(Path(sys.argv[1]), int(sys.argv[2]))
