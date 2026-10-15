"""Run long tasks (import, analysis, export) off the GUI thread with progress + cancel."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from kpmn_tracer.io.decode import CancelledError

log = logging.getLogger(__name__)

TaskFn = Callable[[Callable[[float], None], Callable[[], bool]], Any]


class Worker(QObject):
    progress = Signal(float)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, fn: TaskFn) -> None:
        super().__init__()
        self._fn = fn
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            result = self._fn(self.progress.emit, self._cancel.is_set)
        except CancelledError:
            self.cancelled.emit()
        except Exception as exc:  # report to the UI instead of crashing the thread
            log.exception("Background task failed")
            self.failed.emit(str(exc))
        else:
            if self._cancel.is_set():
                self.cancelled.emit()
            else:
                self.finished.emit(result)


class TaskHandle(QObject):
    """Lives in the GUI thread. Worker signals are relayed (queued) through it, so
    callbacks connected here - including lambdas - always run in the GUI thread."""

    progress = Signal(float)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, worker: Worker, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._worker = worker
        worker.progress.connect(self.progress)
        worker.finished.connect(self.finished)
        worker.failed.connect(self.failed)
        worker.cancelled.connect(self.cancelled)

    def cancel(self) -> None:
        self._worker.cancel()


class TaskRunner(QObject):
    """Owns a QThread per task; keeps references alive until the task ends."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._active: list[tuple[QThread, Worker, TaskHandle]] = []

    def start(self, fn: TaskFn) -> TaskHandle:
        thread = QThread()
        worker = Worker(fn)
        handle = TaskHandle(worker, self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        for sig in (worker.finished, worker.failed, worker.cancelled):
            sig.connect(thread.quit)
        thread.finished.connect(lambda: self._cleanup(thread))
        self._active.append((thread, worker, handle))
        thread.start()
        return handle

    def _cleanup(self, thread: QThread) -> None:
        for t, _w, h in self._active:
            if t is thread:
                h.deleteLater()
        self._active = [e for e in self._active if e[0] is not thread]
        thread.deleteLater()

    def busy(self) -> bool:
        return bool(self._active)

    def cancel_all(self) -> None:
        for _t, w, _h in self._active:
            w.cancel()
        for t, _w, _h in list(self._active):
            t.wait(5000)
