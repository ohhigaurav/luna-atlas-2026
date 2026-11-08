"""Long computations as polled jobs.

A landing ellipse takes 4-5 minutes (measured 8 Nov). Some browsers give up on a single HTTP response
after 300 s, and a 5-minute spinner says nothing. So the client starts a job, then polls it for
``done/total`` points and elapsed time, and finally reads the result. Identical requests share one
job; at most ``max_running`` jobs compute at once, so a burst of requests cannot pile up threads on a
small server. Jobs live in memory: a restart forgets them, but finished answers are also in the
on-disk caches, so asking again is quick.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

Progress = Callable[..., None]


class JobManager:
    def __init__(self, max_running: int = 2, keep: int = 64) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._by_key: dict[str, str] = {}
        self._slots = threading.BoundedSemaphore(max_running)
        self._keep = keep

    def submit(self, key: str, fn: Callable[[Progress], dict[str, Any]]) -> dict[str, Any]:
        """Start ``fn(progress)`` unless an identical job is queued, running or done; return its view."""
        with self._lock:
            existing = self._by_key.get(key)
            if existing in self._jobs and self._jobs[existing]["status"] != "error":
                return self._view(self._jobs[existing])
            job_id = uuid.uuid4().hex[:16]
            job: dict[str, Any] = {"job_id": job_id, "status": "queued", "done": 0, "total": None,
                                   "created": time.time(), "started": None, "finished": None,
                                   "result": None, "error": None, "error_kind": None}
            self._jobs[job_id] = job
            self._by_key[key] = job_id
            self._trim()
        threading.Thread(target=self._run, args=(job, fn), daemon=True, name=f"job-{job_id}").start()
        return self.get(job_id) or {}

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else self._view(job)

    def _run(self, job: dict[str, Any], fn: Callable[[Progress], dict[str, Any]]) -> None:
        with self._slots:
            job["status"], job["started"] = "running", time.time()

            def progress(done: int, total: int, *_: Any) -> None:
                job["done"], job["total"] = done, total

            try:
                job["result"] = fn(progress)
                job["status"] = "done"
            except Exception as exc:  # noqa: BLE001 - reported to the client, never swallowed
                job["status"] = "error"
                job["error"] = f"{type(exc).__name__}: {exc}"
                job["error_kind"] = "invalid" if isinstance(exc, ValueError) else "server"
            finally:
                job["finished"] = time.time()

    def _view(self, job: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        started, finished = job["started"], job["finished"]
        out = {k: job[k] for k in ("job_id", "status", "done", "total", "error", "error_kind")}
        out["queued_s"] = round((started or now) - job["created"], 1)
        out["elapsed_s"] = None if started is None else round((finished or now) - started, 1)
        if job["status"] == "done":
            out["result"] = job["result"]
        return out

    def _trim(self) -> None:
        """Forget the oldest finished jobs beyond ``keep`` (running ones are never dropped)."""
        finished = sorted((j for j in self._jobs.values() if j["finished"] is not None), key=lambda j: j["finished"])
        while len(self._jobs) > self._keep and finished:
            old = finished.pop(0)
            self._jobs.pop(old["job_id"], None)
            for k, v in list(self._by_key.items()):
                if v == old["job_id"]:
                    del self._by_key[k]


ELLIPSE_JOBS = JobManager(max_running=2)
