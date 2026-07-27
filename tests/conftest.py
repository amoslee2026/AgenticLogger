"""Global pytest configuration.

@last-changed: 2026-07-27

Disables AgenticLogger self-observation by default (``AGENTIC_SELF_LOG=0``)
so the whole suite sees no behaviour change and no ``agentic_logger_*.jsonl``
files pollute ``tmp_path``. Subprocess CLI tests inherit this env, so their
child processes stay quiet too.

Tests that exercise self-log explicitly re-enable it via the ``self_log_on``
fixture in ``tests/unit/test_self_log.py``.
"""

import pytest


@pytest.fixture(autouse=True)
def _disable_self_log(monkeypatch):
    """Default-off for AGENTIC_SELF_LOG across the entire suite."""
    monkeypatch.setenv("AGENTIC_SELF_LOG", "0")
