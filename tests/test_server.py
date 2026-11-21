import json
import time

import pytest
from fastapi.testclient import TestClient

from qclip import overview
from qclip.jobs import JobQueue
from qclip.server import create_app
from qclip.steps import Steps, merge_timings, zone_rank


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


def test_job_knows_its_vod_as_soon_as_announced() -> None:
    queue = JobQueue()
    seen: list[str | None] = []

    def work(steps: Steps) -> str:
        steps.video("kick-abc")  # annoncé par le repérage, bien avant la fin
        job = queue.get(1)
        seen.append(job.video_id if job else None)
        return "kick-abc"

    job = queue.submit("process", "Analyse", "demo", work)
    wait(queue, job.id)
    assert seen == ["kick-abc"]


def test_steps_time_stages_and_zones() -> None:
    steps = Steps()
    steps.stage("téléchargement")
    for i in (1, 2):
        with steps.step(f"plage {i:02d}/24"):
            time.sleep(0.01)
    steps.stage("transcription")
    with steps.step("chargement de parakeet"):
        pass
    with steps.step("plage 1/3 (n°22, 75 s)"):  # compteur 1/3, mais c'est la zone 22
        pass
    steps.end_stage()
    assert set(steps.stage_times) == {"téléchargement", "transcription"}
    assert set(steps.zone_times["téléchargement"]) == {1, 2}
    assert set(steps.zone_times["transcription"]) == {22}
    assert [zone_rank(n) for n in ["CLAP plage 05", "score + fenêtres", "plage 3/24"]] == [5, None, 3]
    old = {"audio": 42.0, "chat": 3.0}
    assert merge_timings(old, {"audio": 0.01, "chat": 5.0, "score": 0.1}) == {"audio": 42.0, "chat": 5.0, "score": 0.1}


def test_stage_rates_use_zones_really_processed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(overview, "WORK_DIR", tmp_path)
    assert overview.stage_rates(False) == overview.DEFAULT_RATES
    for name, zones in [("a", [20.0, 24.0]), ("b", [30.0])]:
        (tmp_path / name).mkdir()
        (tmp_path / name / "timings.json").write_text(
            json.dumps({"windows": 24, "stages": {"transcription": 79.0}, "per_zone": {"transcription": zones}}),
            encoding="utf-8",
        )
    rates = overview.stage_rates(True)
    assert rates["transcription"] == 24.0 and rates["séparation"] == overview.SEPARATION_RATE


def test_vod_list(client: TestClient) -> None:
    vods = client.get("/api/vods").json()
    assert isinstance(vods, list)
    assert all({"video_id", "title", "campaign"} <= set(v) for v in vods)


def test_moment_frame_needs_known_vod(client: TestClient) -> None:
    assert client.get("/api/vods/inconnue/moments/1/frame").status_code == 404
    assert client.get("/api/vods/..%2Fqclip/moments/1/frame").status_code == 404


def test_subtitle_font_is_served_for_the_editor_preview(client: TestClient) -> None:
    r = client.get("/media/assets/fonts/Montserrat-ExtraBold.ttf")
    assert r.status_code == 200 and len(r.content) > 100_000
    assert client.get("/media/assets/fonts/../../pyproject.toml").status_code == 404
