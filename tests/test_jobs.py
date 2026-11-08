"""Polled jobs for long computations (lunar_core.jobs): states, sharing, errors, the running cap."""
from __future__ import annotations

import threading
import time
from typing import Any

from lunar_core.jobs import JobManager


def _wait(m: JobManager, job_id: str, status: str, timeout: float = 3.0) -> dict[str, Any]:
    end = time.time() + timeout
    while time.time() < end:
        v = m.get(job_id)
        if v and v["status"] == status:
            return v
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} never reached {status}: {m.get(job_id)}")


def test_job_reports_progress_then_result() -> None:
    m = JobManager()
    gate = threading.Event()

    def work(progress: Any) -> dict[str, Any]:
        progress(3, 45, {"ignored": True})
        gate.wait(2)
        return {"answer": 42}

    v = m.submit("k", work)
    assert v["status"] in ("queued", "running") and "result" not in v
    running = _wait(m, v["job_id"], "running")
    time.sleep(0.05)
    assert m.get(v["job_id"])["done"] == 3 and m.get(v["job_id"])["total"] == 45 and running["elapsed_s"] is not None
    gate.set()
    done = _wait(m, v["job_id"], "done")
    assert done["result"] == {"answer": 42} and done["error"] is None


def test_identical_requests_share_one_job_but_errors_can_be_retried() -> None:
    m = JobManager()
    calls: list[int] = []

    def work(progress: Any) -> dict[str, Any]:
        calls.append(1)
        return {"n": len(calls)}

    a = m.submit("same", work)
    _wait(m, a["job_id"], "done")
    b = m.submit("same", work)
    assert b["job_id"] == a["job_id"] and len(calls) == 1

    def bad(progress: Any) -> dict[str, Any]:
        raise ValueError("unknown site")

    e = m.submit("bad", bad)
    err = _wait(m, e["job_id"], "error")
    assert err["error_kind"] == "invalid" and "unknown site" in err["error"]
    again = m.submit("bad", work)
    assert again["job_id"] != e["job_id"]


def test_at_most_max_running_compute_at_once() -> None:
    m = JobManager(max_running=2)
    release = threading.Event()
    active, peak = [0], [0]
    lock = threading.Lock()

    def work(progress: Any) -> dict[str, Any]:
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        release.wait(2)
        with lock:
            active[0] -= 1
        return {}

    ids = [m.submit(f"k{i}", work)["job_id"] for i in range(4)]
    time.sleep(0.1)
    assert [m.get(i)["status"] for i in ids].count("running") == 2
    assert [m.get(i)["status"] for i in ids].count("queued") == 2
    release.set()
    for i in ids:
        _wait(m, i, "done")
    assert peak[0] == 2


def test_old_finished_jobs_are_forgotten() -> None:
    m = JobManager(keep=3)
    ids = []
    for i in range(6):
        j = m.submit(f"k{i}", lambda p: {})
        _wait(m, j["job_id"], "done")
        ids.append(j["job_id"])
    m.submit("k-new", lambda p: {})
    assert m.get(ids[0]) is None and m.get(ids[-1]) is not None
