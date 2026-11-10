import errno
import os

import pytest

from lib.luna_storage import LunaProviderFailure, SecureJudgeStorage
from lib.state_recovery import TemporaryExhausted


def test_exclusive_cache_collisions_translate_to_provider_failure(tmp_path, monkeypatch) -> None:
    attempted = []
    open_file = os.open

    def collision(path, flags, *args, **kwargs) -> int:
        if flags & os.O_EXCL:
            attempted.append((path, kwargs.get("dir_fd")))
            raise FileExistsError(errno.EEXIST, "occupied")
        return open_file(path, flags, *args, **kwargs)

    with SecureJudgeStorage(runtime_root=tmp_path / "runtime", cache_root=tmp_path / "cache") as storage:
        monkeypatch.setattr(os, "open", collision)

        with pytest.raises(LunaProviderFailure) as failure:
            storage.write_cache("entry.json", "{}")

        assert isinstance(failure.value.__cause__, TemporaryExhausted)
        assert len(attempted) > 1
        assert {directory for _path, directory in attempted} != {None}
        assert storage.read_cache("entry.json") is None


def test_unrelated_cache_allocation_errors_keep_their_original_identity(tmp_path, monkeypatch) -> None:
    error = OSError(errno.EIO, "unrelated storage failure")
    open_file = os.open

    def failed(path, flags, *args, **kwargs) -> int:
        if flags & os.O_EXCL:
            raise error
        return open_file(path, flags, *args, **kwargs)

    with SecureJudgeStorage(runtime_root=tmp_path / "runtime", cache_root=tmp_path / "cache") as storage:
        monkeypatch.setattr(os, "open", failed)

        with pytest.raises(OSError) as failure:
            storage.write_cache("entry.json", "{}")

        assert failure.value is error
        assert storage.read_cache("entry.json") is None
