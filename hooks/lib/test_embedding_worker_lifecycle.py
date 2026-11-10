"""Because model loading can fail, keep worker ownership scoped to the complete serve lifecycle."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from lib import embedding_worker, process_records


@dataclass
class ServeHarness:
    root: Path
    failure: str = ""
    phases: list[tuple[str, set[str]]] = field(default_factory=list)
    closed: bool = False
    stopped: bool = False

    def visit(self, phase: str) -> None:
        roles = {record.role for record in process_records.records(self.root)}
        self.phases.append((phase, roles))
        if self.failure == phase:
            raise ValueError("fixture lifecycle failure")

    def load(self, _directory: Path) -> tuple:
        self.visit("load")
        return object(), object()

    def server(self, _address, _handler) -> FakeServer:
        self.visit("construct")
        return FakeServer(self)

    def watch(self, _root: Path, shutdown) -> None:
        self.visit("watch")
        shutdown()


@dataclass
class FakeServer:
    harness: ServeHarness

    def serve_forever(self) -> None:
        self.harness.visit("serve")

    def server_close(self) -> None:
        self.harness.closed = True

    def shutdown(self) -> None:
        self.harness.stopped = True


def test_worker_registration_precedes_loading_and_ends_after_serving(tmp_path) -> None:
    harness = ServeHarness(tmp_path)

    embedding_worker.serve(tmp_path / "model", 8765, tmp_path, loader=harness.load,
                           server_factory=harness.server, watch=harness.watch)

    assert harness.phases == [
        ("load", {"embedding-worker"}), ("construct", {"embedding-worker"}),
        ("watch", {"embedding-worker"}), ("serve", {"embedding-worker"}),
    ]
    assert harness.closed is True
    assert harness.stopped is True
    assert process_records.records(tmp_path) == []


@pytest.mark.parametrize("phase,closed", [
    pytest.param("load", False, id="loader-failure"),
    pytest.param("construct", False, id="server-construction-failure"),
    pytest.param("watch", True, id="watcher-failure"),
    pytest.param("serve", True, id="serving-failure"),
])
def test_worker_failures_release_ownership_and_created_servers(tmp_path, phase, closed) -> None:
    harness = ServeHarness(tmp_path, phase)

    with pytest.raises(ValueError):
        embedding_worker.serve(tmp_path / "model", 8765, tmp_path, loader=harness.load,
                               server_factory=harness.server, watch=harness.watch)

    assert harness.phases[-1] == (phase, {"embedding-worker"})
    assert harness.closed is closed
    assert process_records.records(tmp_path) == []
