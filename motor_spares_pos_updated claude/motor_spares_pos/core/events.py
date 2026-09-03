"""A tiny in-process "something changed" signal.

Every write that matters anywhere in the POS (a sale, a stock adjustment, a
product edit, a spreadsheet import, a pull of updates from the sync server)
already passes through SyncService.enqueue() or a successful sync. That
makes it the one choke point where we can broadcast "the data changed" to
whatever screen happens to be open, so the admin dashboard (and every other
page) reflects reality within a second of a change happening anywhere —
this terminal or another one, once synced — instead of only refreshing
when the user happens to reopen the page.

This module is intentionally decoupled from the UI: services import and
call emit_change() without knowing or caring whether a UI is even running.
If PySide6 isn't available (e.g. a headless test or script), emit_change()
silently becomes a no-op.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)
_batch_depth = 0
_batch_entities = set()

try:
    from PySide6.QtCore import QObject, Signal

    class _ChangeBus(QObject):
        # entity_type (e.g. "PRODUCT", "SALE", "STOCK_MOVEMENT", "SYNC"), detail dict
        data_changed = Signal(str, object)

    _bus: Optional[_ChangeBus] = _ChangeBus()
except Exception:  # pragma: no cover - headless / no Qt environment
    _bus = None
    logger.info("Qt not available; running without live UI change events")


def emit_change(entity_type: str, detail: Optional[dict] = None) -> None:
    """Broadcast that some data changed. Safe to call from any thread."""
    global _batch_depth
    if _batch_depth:
        _batch_entities.add(entity_type)
        return
    if _bus is None:
        return
    try:
        _bus.data_changed.emit(entity_type, detail or {})
    except Exception:
        logger.exception("Failed to broadcast data change for %s", entity_type)


@contextmanager
def batch_changes(entity_type: str = "DATA"):
    """Coalesce many related writes into one UI change notification."""
    global _batch_depth
    _batch_depth += 1
    try:
        yield
    finally:
        _batch_depth -= 1
        if _batch_depth == 0:
            entities = list(_batch_entities) or [entity_type]
            _batch_entities.clear()
            for changed in entities:
                emit_change(changed)


def subscribe(slot: Callable[[str, Any], None]) -> None:
    """Register a callback to be invoked (on the GUI thread) on every change.

    `slot` should be a bound method of a QObject (e.g. a QWidget/QMainWindow)
    so Qt can safely marshal the call onto that object's own thread even
    when the change was emitted from a background sync/worker thread.
    """
    if _bus is None:
        return
    _bus.data_changed.connect(slot)
