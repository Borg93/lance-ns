"""The guarded Lance-native metrics bridge (pre-wired for the pylance 9 bump) — all three paths."""

from __future__ import annotations

import sys
import types

import pytest
from common.lance_metrics import instrument_lance_if_available


def test_noop_on_pylance_8_where_the_bridge_module_is_absent() -> None:
    # The pinned pylance 8.0.0 has no lance.otel (probed 2026-07-10) — the guard must be a clean no-op
    # so every lifespan hook is safe TODAY, and activation is purely the version bump.
    assert instrument_lance_if_available() is False


def test_activates_when_the_bridge_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []
    fake = types.ModuleType("lance.otel")
    setattr(fake, "instrument_lance_metrics", lambda: calls.append(True))  # noqa: B010
    monkeypatch.setitem(sys.modules, "lance.otel", fake)
    assert instrument_lance_if_available() is True
    assert calls == [True]


def test_bridge_failure_never_raises_into_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> None:
        raise RuntimeError("recorder exploded")

    fake = types.ModuleType("lance.otel")
    setattr(fake, "instrument_lance_metrics", boom)  # noqa: B010
    monkeypatch.setitem(sys.modules, "lance.otel", fake)
    assert instrument_lance_if_available() is False  # logged, swallowed — startup untouched
