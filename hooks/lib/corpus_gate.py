"""Separate module because five test modules would otherwise carry five copies of the same skip reason."""
from __future__ import annotations

import pytest

try:
    from .slop_harness import RuleScope, corpus_path
except ImportError:
    from slop_harness import RuleScope, corpus_path

REBUILD_COMMAND = "python3 evals/build_slop_corpora.py"
SKIP_REASON = (
    "the labelled corpora are third-party samples the punctuation gate refuses to carry, "
    "so they are generated rather than committed: run " + REBUILD_COMMAND
)


def corpora_present() -> bool:
    return all(corpus_path(scope).is_file() for scope in RuleScope)


requires_corpora = pytest.mark.skipif(not corpora_present(), reason=SKIP_REASON)
