"""Durable provider setup receipts shared by every presentation adapter."""

import fcntl
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from .artifacts import digest
from .errors import StoriesError, require
from .store import identity, now


def lease_file(db, job):
    root = Path(db.execute("PRAGMA database_list").fetchone()[2]).parent
    return root / ("setup-owner-" + digest(job["id"]) + ".lock")


def reconcile_job(db, job):
    """Deadline requests stop, not completed cleanup. A kernel lease proves ownership.

    The worker holds an exclusive flock through cleanup. Lock availability after
    admission was claimed proves that owner exited, independent of PID reuse.
    Unclaimed expired admissions are atomically fenced before any late worker can run.
    """
    if job["status"] not in {"running", "cancelling", "timing_out"}:
        return job
    if job.get("owner_claimed"):
        with lease_file(db, job).open("a") as lease:
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                job.update(
                    status="failed",
                    error={
                        "code": "setup_owner_lost",
                        "message": "Setup owner exited without a settled result. No replay.",
                    },
                    finished_at=now(),
                )
    if job["status"] in {"running", "cancelling"} and job["deadline"] <= now():
        job.update(
            status="timing_out" if job.get("owner_claimed") or job.get("pid") else "failed",
            error={
                "code": "setup_timeout",
                "message": "Setup deadline elapsed; waiting for owned cleanup. No automatic retry.",
            },
        )
    from .store import Store

    Store.put(db, "provider_jobs", job)
    return job


def active_jobs(db):
    jobs = [
        reconcile_job(db, json.loads(row[0]))
        for row in db.execute("SELECT data FROM provider_jobs").fetchall()
    ]
    return [job for job in jobs if job["status"] in {"running", "cancelling", "timing_out"}]


class ProviderJobLibrary:
    def start_provider_job(self, kind, request_id, provider=None, model=None):
        """Explicit setup/test/login/discovery with a durable exact-retry receipt; model_env required.

        Setup may install runtime modules, login may change provider-owned credentials,
        and test sends one small model request. Neither status nor retries repeat work.
        """
        from .providers import ProviderConfig

        require(kind in {"prepare", "test", "models", "login"}, "Unknown provider action.")
        require(isinstance(request_id, str) and 0 < len(request_id) <= 200, "A request_id is required.")
        fingerprint = digest(json.dumps(["provider_job", kind, provider, model], sort_keys=True))
        with self.store.transaction() as db:
            prior = db.execute("SELECT digest,result FROM requests WHERE id=?", (request_id,)).fetchone()
            if prior:
                require(
                    prior[0] == fingerprint,
                    "request_id already used with different input.",
                    "request_conflict",
                )
                return json.loads(prior[1])
            require(self.model_env, "Enable model_env for provider setup.", "model_access_required")
            config = ProviderConfig(
                provider or self.config.provider,
                model if model is not None or provider is not None else self.config.model,
                use_env=False,
            )
            require(not active_jobs(db), "Another provider action is running.", "provider_busy")
            require(
                not any(
                    json.loads(row[0])["state"] in {"queued", "running"}
                    for row in db.execute("SELECT data FROM operations")
                ),
                "Wait for current work to finish before provider setup.",
                "provider_busy",
            )
            job = {
                "id": identity("setup"),
                "status": "running",
                "kind": kind,
                **config.public(),
                "messages": [],
                "created_at": now(),
                "deadline": now() + 310,
            }
            self.store.put(db, "provider_jobs", job)
            receipt = {"job_id": job["id"], "status": "running", "kind": kind, **config.public()}
            db.execute("INSERT INTO requests VALUES (?,?,?)", (request_id, fingerprint, json.dumps(receipt)))
        # Admission is committed before dispatch. A lost dispatch is never replayed.
        try:
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "amplifier_smart_tool_stories.provider_jobs",
                    str(self.store.path),
                    job["id"],
                    "--model-env",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            with self.store.transaction() as db:
                job.update(
                    status="failed",
                    error={
                        "code": "setup_dispatch_failed",
                        "message": "Provider worker could not start; use a new request for new intent.",
                    },
                )
                self.store.put(db, "provider_jobs", job)
        return receipt

    def get_provider_job(self, job_id=None):
        """Read a setup job or the latest store job; expired ownership fails without replay."""
        with self.store.transaction() as db:
            if job_id is None:
                jobs = [json.loads(row[0]) for row in db.execute("SELECT data FROM provider_jobs")]
                if not jobs:
                    return {"status": "idle", "messages": []}
                job = max(jobs, key=lambda row: row["created_at"])
            else:
                job = self.store.get(db, "provider_jobs", job_id)
            return reconcile_job(db, job)

    def cancel_provider_job(self, job_id):
        """Cancel this exact setup job; the worker releases its owned provider resources."""
        with self.store.transaction() as db:
            job = self.store.get(db, "provider_jobs", job_id)
            if job["status"] == "running":
                job.update(status="cancelling" if job.get("pid") else "cancelled")
                self.store.put(db, "provider_jobs", job)
            return job


def run(storage, job_id):
    from .store import Store

    store = Store(storage)
    lease = None
    try:
        with store.transaction() as db:
            job = reconcile_job(db, store.get(db, "provider_jobs", job_id))
            if job["status"] != "running" or job.get("owner_claimed") or job.get("pid"):
                return
            lease = lease_file(db, job).open("a")
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            job.update(pid=os.getpid(), owner_claimed=True)
            store.put(db, "provider_jobs", job)
        _run_owned(storage, job_id, job)
    finally:
        if lease:
            lease.close()


def _run_owned(storage, job_id, job):
    from .lib import Stories
    from .providers import _job_context

    api = Stories(storage, model_env=True)
    from .providers import ProviderConfig

    api.config = ProviderConfig(job["provider"], job["model"], use_env=False)
    stopped = threading.Event()
    previous_cancel = getattr(_job_context, "cancel", None)
    _job_context.cancel = stopped

    def watch():
        while not stopped.wait(0.1):
            if api.get_provider_job(job_id)["status"] != "running":
                stopped.set()

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()

    def progress(text):
        with api.store.transaction() as db:
            current = api.store.get(db, "provider_jobs", job_id)
            if current["status"] == "running":
                current["messages"] = (current["messages"] + [str(text)[:2000]])[-30:]
                api.store.put(db, "provider_jobs", current)

    try:
        result = {
            "prepare": api.prepare_runtime,
            "test": api.test_provider,
            "models": api.provider_models,
            "login": lambda: api.provider_login(on_progress=progress),
        }[job["kind"]]()
        outcome = {"status": "succeeded", "result": result}
    except StoriesError as exc:
        outcome = {"status": "failed", "error": exc.public()["error"]}
    except Exception:
        outcome = {
            "status": "failed",
            "error": {
                "code": "setup_failed",
                "message": "Provider setup failed. Inspect configuration before a new request.",
            },
        }
    finally:
        stopped.set()
        watcher.join(timeout=1)
        _job_context.cancel = previous_cancel
    with api.store.transaction() as db:
        current = api.store.get(db, "provider_jobs", job_id)
        if current["status"] in {"running", "cancelling", "timing_out"}:
            current.update(
                {"status": "failed"}
                if current["status"] == "timing_out"
                else {"status": "cancelled"}
                if current["status"] == "cancelling"
                else outcome,
                finished_at=time.time(),
            )
            api.store.put(db, "provider_jobs", current)


if __name__ == "__main__":
    require(len(sys.argv) == 4 and sys.argv[3] == "--model-env", "Explicit provider access required.")
    run(sys.argv[1], sys.argv[2])
