import shutil

import numpy as np
import pytest

from qclip.safety import FIRST_SECONDS, check, events

LABELS = ["people laughing", "explosion", "gunshots", "car crash"]


def word(text: str, start: float) -> dict:
    return {"text": text, "start": start, "end": start + 0.3}


def test_profanity_in_first_seconds_is_flagged_with_smallest_shift() -> None:
    words = [word("Bonjour", 100.0), word("putain", 102.0), word("regarde", 104.0), word("merde", 115.0)]
    found = events(words, None, None, LABELS)
    verdict = check(100.0, 130.0, found, min_len=15)
    assert not verdict["ok"] and verdict["flags"][0] == {"kind": "gros mot", "at": 2.0, "detail": "putain"}
    # Juste après « putain » (102,3 + 0,2) : les 7 s suivantes vont jusqu'à 109,5, « merde » (115) n'y est pas.
    assert verdict["shift_s"] == 2.5
    assert check(110.0, 130.0, found, min_len=15)["shift_s"] is None  # décaler passerait sous 15 s
    assert check(103.0, 130.0, found, min_len=15)["ok"]  # « putain » est avant le début


def test_violent_sounds_but_not_car_crash() -> None:
    times = np.arange(0, 20, 0.5) + 200.0
    clap = np.zeros((len(times), len(LABELS)))
    clap[:, 3] = 0.65  # « car crash » constant : bruit de fond d'un stream, ignoré
    clap[8, 2] = 0.8  # coups de feu à 204 s
    found = events([], clap, times, LABELS)
    assert [e["detail"] for e in found] == ["coups de feu (0.80)"]
    verdict = check(200.0, 230.0, found, min_len=15)
    assert verdict["flags"][0]["kind"] == "violence" and verdict["flags"][0]["at"] == 3.8
    assert verdict["shift_s"] is not None and verdict["shift_s"] >= 4.0
    assert check(205.0 + 0.1, 230.0, found, min_len=15)["ok"]
    assert FIRST_SECONDS == 7.0


def test_vision_verdict_adds_a_readable_flag(monkeypatch, tmp_path) -> None:
    """Images violentes : drapeau « image » (lisible par le pipeline et l'éditeur), pas de décalage automatique."""
    import json

    import qclip.vision
    from qclip import render

    windows = tmp_path / "vid" / "windows"
    windows.mkdir(parents=True)
    (windows / "windows.json").write_text(json.dumps([{"rank": 1, "start": 100.0, "duration": 85.0}]), "utf-8")
    monkeypatch.setattr("qclip.sources.WORK_DIR", tmp_path)
    c = {"window": 1, "start": 110.0, "end": 140.0}
    words = [word("putain", 112.0)]

    seen = {"flagged": True, "at": [2.5], "description": "une bagarre avec du sang", "seconds": 90.0}
    monkeypatch.setattr(qclip.vision, "check_images", lambda clip, thumb, model: seen)
    v = render.clip_safety("vid", c, words, LABELS, 15, clip=tmp_path / "c.mp4", vision_model="m")
    assert not v["ok"] and v["vision"] is seen and v["shift_s"] is None
    assert v["flags"][-1] == {"kind": "image", "at": 2.5, "detail": "une bagarre avec du sang"}

    def down(clip, thumb, model):
        raise RuntimeError("Ollama injoignable")

    monkeypatch.setattr(qclip.vision, "check_images", down)
    v = render.clip_safety("vid", c, words, LABELS, 15, clip=tmp_path / "c.mp4", vision_model="m")
    assert v["vision"] == {"error": "Ollama injoignable"} and v["shift_s"] == 2.5  # le verdict son + mots reste
    assert render.clip_safety("vid", c, [], LABELS, 15)["vision"] is None  # images non vérifiées


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent")
def test_vision_frame_reads_a_still_thumbnail(tmp_path) -> None:
    """Bug trouvé en M6 : `-ss 0` sur une image fixe → ffmpeg n'écrit rien (code 0) → miniature jamais vérifiée."""
    from qclip.utils.ffmpeg import run
    from qclip.vision import frame

    thumb = tmp_path / "clip.jpg"
    assert run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=1080x1920", "-frames:v", "1",
                thumb]).returncode == 0  # fmt: skip
    out = frame(thumb, 0, tmp_path / "out.jpg")
    assert out.exists() and out.stat().st_size > 0
