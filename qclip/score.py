"""Scoring fin et choix du meilleur passage de chaque plage (SPEC §4.5). Fonctions pures, testées (test_score.py).

Règles : pic → quelques secondes de contexte avant, fin après la retombée ; début en début de phrase, fin en fin de
phrase ou de mot (jamais au milieu d'un mot) ; longueur dans les bornes du brief ; coupe de scène proche = point de
coupe privilégié.
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np

SENTENCE_END = (".", "?", "!", "…")
PAUSE = 0.6  # un silence d'au moins 0,6 s entre deux mots compte comme une frontière de phrase
CUT_SNAP = 1.0  # une coupe de scène à moins d'1 s d'une borne devient la borne
END_AFTER_DROP = 5.0  # secondes gardées après la retombée de l'excitation (borne haute de la spec : 2 à 5 s)
DROP_RATIO = 0.35  # « retombée » : le score lissé passe sous 35 % de la hauteur du pic
WORD_PAD = 0.15  # marge avant le premier mot / après le dernier
TARGET_TOLERANCE = 3.0  # on s'arrête à 3 s de la durée cible


@dataclass
class Segment:
    start: float
    end: float
    peak: float
    reasons: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


def pooled_z(arrays: list[np.ndarray]) -> list[np.ndarray]:
    """z-score commun à toutes les plages : un signal n'est fort que s'il dépasse le niveau habituel de la VOD."""
    values = np.concatenate([a for a in arrays if len(a)]) if arrays else np.zeros(0)
    if len(values) == 0:
        return [np.zeros_like(a, dtype=np.float64) for a in arrays]
    mean, std = float(values.mean()), float(values.std())
    if std < 1e-9:
        return [np.zeros_like(a, dtype=np.float64) for a in arrays]
    return [(a - mean) / std for a in arrays]


def smooth(x: np.ndarray, width: int) -> np.ndarray:
    if width <= 1 or len(x) == 0:
        return x.astype(np.float64)
    return np.convolve(x, np.ones(width) / width, mode="same")


def sentence_starts(words: list[dict[str, Any]]) -> list[int]:
    """Indices des mots qui ouvrent une phrase (après une ponctuation finale ou une pause)."""
    starts = [0] if words else []
    for i in range(1, len(words)):
        prev = words[i - 1]
        if prev["text"].rstrip().endswith(SENTENCE_END) or words[i]["start"] - prev["end"] >= PAUSE:
            starts.append(i)
    return starts


def sentence_ends(words: list[dict[str, Any]]) -> list[int]:
    """Indices des mots qui ferment une phrase."""
    return [s - 1 for s in sentence_starts(words)[1:]] + ([len(words) - 1] if words else [])


def first_word_at(words: list[dict[str, Any]], t: float) -> int:
    """Premier mot qui finit après t (le mot « en cours » à l'instant t)."""
    for i, w in enumerate(words):
        if w["end"] > t:
            return i
    return len(words) - 1


def choose_segment(
    times: np.ndarray,
    score: np.ndarray,
    words: list[dict[str, Any]],
    cuts: list[float],
    min_len: float,
    max_len: float,
    preroll: float,
    bounds: tuple[float, float],
    target_len: float | None = None,
) -> Segment:
    """Meilleur passage de la plage : autour du pic de `score`, calé sur les phrases, dans [min_len, max_len],
    rallongé phrase par phrase vers `target_len` s'il est donné."""
    lo, hi = bounds
    i_peak = int(np.argmax(score))
    peak = float(times[i_peak])
    height = score[i_peak] - float(np.median(score))
    drop = next(
        (float(times[j]) for j in range(i_peak, len(score)) if score[j] - np.median(score) < DROP_RATIO * height),
        float(times[-1]),
    )
    start, end = peak - preroll, drop + END_AFTER_DROP

    if words:
        starts, ends = sentence_starts(words), sentence_ends(words)
        # Début : la phrase en cours au moment « pic − preroll ».
        k = first_word_at(words, start)
        s_idx = max((s for s in starts if s <= k), default=0)
        # Fin : la première fin de phrase après la fin visée (sinon le dernier mot).
        k_end = first_word_at(words, end)
        e_idx = min((e for e in ends if e >= k_end), default=len(words) - 1)
        # Trop court : on ajoute des phrases avant (contexte), puis après.
        while words[e_idx]["end"] - words[s_idx]["start"] < min_len:
            before = [s for s in starts if s < s_idx]
            after = [e for e in ends if e > e_idx]
            if before and peak - words[before[-1]]["start"] <= max_len * 0.6:
                s_idx = before[-1]
            elif after:
                e_idx = after[0]
            elif before:
                s_idx = before[-1]
            else:
                break
        # Durée cible : on ajoute des phrases entières, avant ou après, celle qui rapproche le plus de la cible.
        # Avant seulement si le pic reste dans la première moitié du clip (le moment fort doit arriver vite).
        if target_len:
            while words[e_idx]["end"] - words[s_idx]["start"] < target_len - TARGET_TOLERANCE:
                options = []
                before = [i for i in starts if i < s_idx]
                after = [e for e in ends if e > e_idx]
                if before and peak - words[before[-1]]["start"] <= target_len / 2:
                    options.append((before[-1], e_idx))
                if after:
                    options.append((s_idx, after[0]))
                options = [o for o in options if words[o[1]]["end"] - words[o[0]]["start"] <= max_len]
                if not options:
                    break
                s_idx, e_idx = min(options, key=lambda o: abs(words[o[1]]["end"] - words[o[0]]["start"] - target_len))
        # Trop long : on retire des phrases au début (sans dépasser le pic), puis on coupe la fin à une fin de mot.
        while words[e_idx]["end"] - words[s_idx]["start"] > max_len:
            later = [s for s in starts if s_idx < s and words[s]["start"] <= peak - 1]
            if later:
                s_idx = later[0]
                continue
            fitting = [e for e in ends if s_idx <= e < e_idx and words[e]["end"] - words[s_idx]["start"] <= max_len]
            if fitting:
                e_idx = fitting[-1]
            else:
                while e_idx > s_idx and words[e_idx]["end"] - words[s_idx]["start"] > max_len:
                    e_idx -= 1
            break
        start = words[s_idx]["start"] - WORD_PAD
        end = words[e_idx]["end"] + WORD_PAD
        if s_idx > 0:
            start = max(start, words[s_idx - 1]["end"])  # la marge ne mord pas sur le mot précédent
        if e_idx + 1 < len(words):
            end = min(end, words[e_idx + 1]["start"])
        start, end = snap_to_cuts(start, end, cuts, words)

    # Sans transcription (ou passage hors de la plage) : bornes brutes, ramenées dans la plage et le brief.
    start, end = max(lo, start), min(hi, end)
    if end - start < min_len:
        end = min(hi, start + min_len)
        start = max(lo, end - min_len)
    if end - start > max_len:
        start = max(start, min(peak - preroll, end - max_len))
        end = start + max_len
    return Segment(round(start, 3), round(end, 3), round(peak, 3))


def snap_to_cuts(start: float, end: float, cuts: list[float], words: list[dict[str, Any]]) -> tuple[float, float]:
    """Une coupe de scène proche d'une borne la remplace, si elle ne tombe pas au milieu d'un mot."""

    def inside_word(t: float) -> bool:
        return any(w["start"] < t < w["end"] for w in words)

    near_start = [c for c in cuts if abs(c - start) <= CUT_SNAP and not inside_word(c)]
    near_end = [c for c in cuts if abs(c - end) <= CUT_SNAP and not inside_word(c)]
    if near_start:
        start = min(near_start, key=lambda c: abs(c - start))
    if near_end:
        end = min(near_end, key=lambda c: abs(c - end)) - 0.04  # finir juste avant le nouveau plan
    return start, end


def overlap_ratio(a: tuple[float, float], b: tuple[float, float]) -> float:
    inter = min(a[1], b[1]) - max(a[0], b[0])
    return max(0.0, inter) / max(1e-9, min(a[1] - a[0], b[1] - b[0]))


def dedupe(candidates: list[dict[str, Any]], max_overlap: float = 0.3) -> list[dict[str, Any]]:
    """Garde le meilleur de deux candidats qui se recouvrent à plus de max_overlap (de la durée du plus court)."""
    kept: list[dict[str, Any]] = []
    for c in sorted(candidates, key=lambda c: c["score"], reverse=True):
        if all(overlap_ratio((c["start"], c["end"]), (k["start"], k["end"])) <= max_overlap for k in kept):
            kept.append(c)
    return kept
