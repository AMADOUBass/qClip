from collections.abc import Sequence

import numpy as np
import pytest

from qclip.score import (
    choose_segment,
    dedupe,
    overlap_ratio,
    pooled_z,
    sentence_ends,
    sentence_starts,
    snap_to_cuts,
)
from qclip.signals import STEP


def make_words(sentences: Sequence[str], start: float = 100.0, word_s: float = 0.4, pause: float = 0.8) -> list[dict]:
    """Phrases → mots horodatés : chaque mot dure word_s, une pause entre deux phrases."""
    words, t = [], start
    for sentence in sentences:
        for token in sentence.split():
            words.append({"text": token, "start": round(t, 3), "end": round(t + word_s, 3), "confidence": 0.9})
            t += word_s
        t += pause
    return words


SENTENCES = [
    "Bon les gars on reprend.",
    "Écoute-moi bien je vais te raconter un truc.",
    "Hier soir j'étais au camp avec les autres.",
    "Et là il sort de nulle part le mec.",
    "Wesh c'est pas possible t'as vu ça ?",
    "On a tous rigolé pendant dix minutes.",
    "Bref on passe à autre chose.",
    "Qui veut jouer ce soir ?",
]


def peak_score(times: np.ndarray, peak: float, width: float = 3.0) -> np.ndarray:
    return np.exp(-(((times - peak) / width) ** 2))


def test_pooled_z_compares_windows_to_each_other() -> None:
    calm, loud = np.full(10, 1.0), np.full(10, 3.0)
    z_calm, z_loud = pooled_z([calm, loud])
    assert np.allclose(z_calm, -1) and np.allclose(z_loud, 1)
    assert all(np.all(z == 0) for z in pooled_z([np.full(5, 2.0), np.full(5, 2.0)]))


def test_sentence_boundaries() -> None:
    words = make_words(["Salut toi.", "Ça va?"])
    assert sentence_starts(words) == [0, 2]
    assert sentence_ends(words) == [1, 3]
    # une pause longue sans ponctuation compte aussi
    assert sentence_starts(make_words(["un deux", "trois"], pause=0.7)) == [0, 2]
    assert sentence_starts(make_words(["un deux", "trois"], pause=0.2)) == [0]


def test_segment_starts_on_sentence_and_respects_bounds() -> None:
    words = make_words(SENTENCES)
    times = np.arange(98.0, words[-1]["end"] + 3, STEP)
    reaction = next(w for w in words if w["text"] == "Wesh")["start"]
    seg = choose_segment(times, peak_score(times, reaction), words, [], 15, 59, 3.0, (98.0, float(times[-1])))
    starts = {w["start"] for w in words}
    ends = {w["end"] for w in words}
    assert 15 <= seg.duration <= 59
    assert seg.start <= reaction <= seg.end
    # début = début d'un mot (moins la marge), fin = fin d'un mot (plus la marge) : aucun mot coupé
    assert any(abs(seg.start - (s - 0.15)) < 1e-6 for s in starts)
    assert any(abs(seg.end - (e + 0.15)) < 1e-6 for e in ends)
    first = min((w for w in words if w["start"] >= seg.start), key=lambda w: w["start"])
    i = words.index(first)
    assert i == 0 or words[i - 1]["text"].endswith((".", "?", "!"))  # le clip commence en début de phrase
    for w in words:
        assert not (w["start"] < seg.start < w["end"]) and not (w["start"] < seg.end < w["end"])


def test_segment_respects_max_len() -> None:
    long_sentences = [" ".join(["mot"] * 40) + "." for _ in range(4)]  # phrases de 16 s
    words = make_words(long_sentences)
    times = np.arange(98.0, words[-1]["end"] + 3, STEP)
    peak = words[60]["start"]
    seg = choose_segment(times, peak_score(times, peak, 20), words, [], 15, 30, 3.0, (98.0, float(times[-1])))
    assert seg.duration <= 30 + 1e-6
    assert seg.start <= peak <= seg.end


def test_segment_without_transcript_uses_raw_bounds() -> None:
    times = np.arange(0.0, 85.0, STEP)
    seg = choose_segment(times, peak_score(times, 40.0), [], [], 15, 59, 3.0, (0.0, 85.0))
    assert seg.start == pytest.approx(37.0)
    assert 15 <= seg.duration <= 59


def test_segment_clamped_to_window() -> None:
    times = np.arange(0.0, 85.0, STEP)
    seg = choose_segment(times, peak_score(times, 1.0), [], [], 15, 59, 3.0, (0.0, 85.0))
    assert seg.start >= 0.0 and seg.end <= 85.0 and seg.duration >= 15


def test_snap_to_cuts_never_inside_a_word() -> None:
    words = [{"text": "mot", "start": 10.0, "end": 10.5}]
    assert snap_to_cuts(9.0, 30.0, [9.6], words) == (9.6, 30.0)
    assert snap_to_cuts(9.9, 30.0, [10.2], words) == (9.9, 30.0)  # 10.2 tombe dans « mot »
    assert snap_to_cuts(9.0, 30.0, [30.5], words) == (9.0, pytest.approx(30.46))


def test_dedupe_keeps_best_of_overlapping() -> None:
    cands = [
        {"start": 0, "end": 30, "score": 1.0},
        {"start": 10, "end": 40, "score": 2.0},  # recouvre le 1er à 67 % → seul le meilleur reste
        {"start": 100, "end": 130, "score": 0.5},
    ]
    kept = dedupe(cands)
    assert [c["score"] for c in kept] == [2.0, 0.5]
    assert overlap_ratio((0, 30), (10, 40)) == pytest.approx(20 / 30)


def test_segment_grows_toward_target_with_whole_sentences() -> None:
    words = make_words(SENTENCES * 2)  # ~65 s de parole
    times = np.arange(98.0, words[-1]["end"] + 3, STEP)
    reaction = [w for w in words if w["text"] == "Wesh"][0]["start"]
    bounds = (98.0, float(times[-1]))
    short = choose_segment(times, peak_score(times, reaction), words, [], 15, 59, 3.0, bounds)
    seg = choose_segment(times, peak_score(times, reaction), words, [], 15, 59, 3.0, bounds, target_len=30)
    assert seg.duration > short.duration
    assert 27 <= seg.duration <= 59
    assert seg.peak - seg.start <= 15 + 1  # le pic reste dans la première moitié de la cible
    ends = {w["end"] for w in words}
    assert any(abs(seg.end - (e + 0.15)) < 1e-6 for e in ends)  # toujours en fin de mot
    first = min((w for w in words if w["start"] >= seg.start), key=lambda w: w["start"])
    i = words.index(first)
    assert i == 0 or words[i - 1]["text"].endswith((".", "?", "!"))  # toujours en début de phrase
