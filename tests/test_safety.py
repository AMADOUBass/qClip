import numpy as np

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
