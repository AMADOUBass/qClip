"""File de tâches longues pour l'interface (SPEC §7) : une seule à la fois (un seul gros modèle en mémoire).

Chaque tâche reçoit un `Steps` dont les callbacks mettent à jour son état ; l'API lit ces états (SSE).
"""

import itertools
import re
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from qclip.steps import Steps

COUNT_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
MAX_LOGS = 200


@dataclass
class Job:
    id: int
    kind: str  # process | render | rerank | meta
    label: str
    campaign: str
    video_id: str | None = None
    status: str = "queued"  # queued | running | done | error
    stage: str = ""
    step: str = ""
    progress: tuple[int, int] | None = None  # « 14/24 » de l'étape en cours
    eta_s: float | None = None  # temps restant estimé pour l'étape en cours
    stage_times: dict[str, float] = field(default_factory=dict)  # durée de chaque grande étape terminée
    logs: list[str] = field(default_factory=list)
    error: str = ""
    result: Any = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    ended_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        now = self.ended_at or time.time()
        data["elapsed_s"] = round(now - self.started_at, 1) if self.started_at else 0.0
        return data


class JobQueue:
    def __init__(self) -> None:
        self._jobs: dict[int, Job] = {}
        self._pending: list[tuple[Job, Callable[[Steps], Any]]] = []
        self._ids = itertools.count(1)
        self._cond = threading.Condition()
        self._stage_start: dict[int, float] = {}  # début de la grande étape en cours, par tâche
        self.version = 0  # augmente à chaque changement : l'API attend dessus pour pousser les mises à jour
        self._worker = threading.Thread(target=self._run, name="qclip-jobs", daemon=True)
        self._worker.start()

    def submit(
        self, kind: str, label: str, campaign: str, fn: Callable[[Steps], Any], video_id: str | None = None
    ) -> Job:
        with self._cond:
            job = Job(next(self._ids), kind, label, campaign, video_id)
            self._jobs[job.id] = job
            self._pending.append((job, fn))
            self._changed()
            return job

    def get(self, job_id: int) -> Job | None:
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.id, reverse=True)

    def current(self) -> Job | None:
        return next((j for j in self._jobs.values() if j.status == "running"), None)

    def wait_change(self, seen: int, timeout: float = 15.0) -> int:
        """Bloque jusqu'à un changement (ou le délai) ; renvoie la nouvelle version."""
        with self._cond:
            self._cond.wait_for(lambda: self.version != seen, timeout=timeout)
            return self.version

    def _changed(self) -> None:
        self.version += 1
        self._cond.notify_all()

    def _steps(self, job: Job) -> Steps:
        done_durations: list[float] = []
        self._stage_start[job.id] = time.time()

        def update(**changes: Any) -> None:
            with self._cond:
                for key, value in changes.items():
                    setattr(job, key, value)
                self._changed()

        def on_stage(name: str) -> None:
            if job.stage:
                job.stage_times[job.stage] = round(time.time() - self._stage_start[job.id], 1)
            self._stage_start[job.id] = time.time()
            done_durations.clear()
            update(stage=name, step="", progress=None, eta_s=None)

        def on_start(name: str) -> None:
            match = COUNT_RE.search(name)
            progress = (int(match.group(1)) - 1, int(match.group(2))) if match else job.progress
            update(step=name, progress=progress)

        def on_done(name: str, seconds: float) -> None:
            match = COUNT_RE.search(name)
            eta = None
            progress = job.progress
            if match:
                done, total = int(match.group(1)), int(match.group(2))
                done_durations.append(seconds)
                eta = round(sum(done_durations) / len(done_durations) * (total - done), 1)
                progress = (done, total)
            logs = [*job.logs, f"{name} — {seconds:.1f} s"][-MAX_LOGS:]
            update(progress=progress, eta_s=eta, logs=logs)

        def on_info(message: str) -> None:
            update(logs=[*job.logs, message][-MAX_LOGS:])

        def on_video(vid: str) -> None:
            update(video_id=vid)

        return Steps(on_start=on_start, on_done=on_done, on_info=on_info, on_stage=on_stage, on_video=on_video)

    def _run(self) -> None:
        while True:
            with self._cond:
                self._cond.wait_for(lambda: bool(self._pending))
                job, fn = self._pending.pop(0)
                job.status, job.started_at = "running", time.time()
                self._changed()
            try:
                result = fn(self._steps(job))
                with self._cond:
                    if job.stage:
                        started = self._stage_start.get(job.id, job.started_at or time.time())
                        job.stage_times[job.stage] = round(time.time() - started, 1)
                    job.status, job.result, job.ended_at = "done", result, time.time()
                    if isinstance(result, str) and job.video_id is None:
                        job.video_id = result
                    self._changed()
            except Exception as e:  # une tâche qui échoue ne doit jamais arrêter la file
                with self._cond:
                    job.status, job.error, job.ended_at = "error", str(e) or type(e).__name__, time.time()
                    job.logs = [*job.logs, traceback.format_exc(limit=3)][-MAX_LOGS:]
                    self._changed()
