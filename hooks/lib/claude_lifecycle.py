"""Separate provider work because settings locks must end before a model call completes."""
from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Callable, Iterator


@dataclass(frozen=True, slots=True)
class LunaSettings:
    settings_path: Path
    preset_path: Path
    generation: tuple[object, ...]


SettingsGate = Callable[..., AbstractContextManager[LunaSettings | None]]


@dataclass(frozen=True, slots=True)
class _LunaOperation:
    """Gate reserved calls because model work must start against stable settings."""

    owner: LunaOperations
    settings: LunaSettings

    def invoke(self, call: Callable[[object], object], request: object) -> object | None:
        with self.owner.gate(settings_path=self.settings.settings_path, preset_path=self.settings.preset_path) as current:
            if current != self.settings or not self.owner.active(self):
                return None
        return call(request)


class LunaOperations:
    """Keep reservations local because provider work must not own the settings transaction."""

    def __init__(self, gate: SettingsGate) -> None:
        self.gate = gate
        self._reservations: dict[Path, _LunaOperation] = {}
        self._lock = threading.Lock()

    def active(self, operation: _LunaOperation) -> bool:
        with self._lock:
            return self._reservations.get(operation.settings.preset_path) is operation

    def release(self, operation: _LunaOperation) -> None:
        with self._lock:
            if self._reservations.get(operation.settings.preset_path) is operation:
                del self._reservations[operation.settings.preset_path]

    def _reserve(self, settings: LunaSettings) -> _LunaOperation | None:
        with self._lock:
            if settings.preset_path in self._reservations:
                return None
            operation = _LunaOperation(self, settings)
            self._reservations[settings.preset_path] = operation
            return operation

    @contextmanager
    def __call__(
        self, *, settings_path: str | Path | None = None,
        preset_path: str | Path | None = None,
    ) -> Iterator[_LunaOperation | None]:
        """Release the reservation lock early because provider calls may wait on settings."""
        with self.gate(settings_path=settings_path, preset_path=preset_path) as settings:
            operation = None if settings is None else self._reserve(settings)
        if operation is None:
            yield None
            return
        try:
            yield operation
        finally:
            self.release(operation)
