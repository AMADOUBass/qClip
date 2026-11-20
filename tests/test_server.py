import time

import pytest
from fastapi.testclient import TestClient

from qclip.jobs import JobQueue
from qclip.server import create_app
from qclip.steps import Steps


def wait(queue: JobQueue, job_id: int, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = queue.get(job_id)
        assert job is not None
        if job.status in {"done", "error"}:
            return job.to_dict()
        time.sleep(0.02)
    raise AssertionError("la tâche ne s'est pas terminée")


def test_job_queue_tracks_stages_progress_and_errors() -> None:
    queue = JobQueue()

    def work(steps: Steps) -> str:
        steps.stage("téléchargement")
        for i in range(1, 4):
            with steps.step(f"plage {i}/3"):
                time.sleep(0.01)
        steps.stage("transcription")
        steps.info("3 plages prêtes")
        return "twitch-1"

    def broken(steps: Steps) -> None:
        steps.stage("repérage")
        raise RuntimeError("Kick a refusé la connexion (403)")

    ok = queue.submit("process", "Analyse", "demo", work)
    ko = queue.submit("process", "Analyse cassée", "demo", broken)
    after = queue.submit("process", "Analyse suivante", "demo", work)
    done = wait(queue, ok.id)
    assert done["status"] == "done" and done["video_id"] == "twitch-1"
    assert any(line.startswith("plage 3/3 — ") for line in done["logs"])
    assert done["progress"] is None and done["stage"] == "transcription"  # progression remise à zéro à chaque étape
    assert set(done["stage_times"]) == {"téléchargement", "transcription"}
    assert "3 plages prêtes" in done["logs"]
    failed = wait(queue, ko.id)
    assert failed["status"] == "error" and "403" in failed["error"]
    assert wait(queue, after.id)["status"] == "done"  # une erreur n'arrête pas la file


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(JobQueue()))


def test_media_is_confined_to_data_folders(client: TestClient) -> None:
    assert client.get("/media/pyproject.toml").status_code == 404
    assert client.get("/media/work/../pyproject.toml").status_code == 404
    assert client.get("/media/campaigns/_template.yaml").status_code == 404  # campaigns/ hors assets/


def test_api_errors_are_clear(client: TestClient) -> None:
    r = client.get("/api/vods/inconnue")
    assert r.status_code == 404 and "inconnue" in r.json()["detail"]
    r = client.post("/api/campaigns", json={"brief": {}})
    assert r.status_code == 400 and "slug" in r.json()["detail"]
    assert client.get("/api/jobs/999").status_code == 404
    assert client.get("/api/system").json()["ram_total_gb"] > 0
