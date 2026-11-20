"""Interface commune des backends de transcription (SPEC §4.4)."""

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

WORD_TAIL = 0.4  # durée max attribuée au dernier token d'un mot (s) ; évite qu'un mot « dure » pendant un silence


@dataclass
class Word:
    text: str
    start: float  # secondes, relatives au fichier audio transcrit
    end: float
    confidence: float | None  # 0 à 1 ; None si le backend ne la fournit pas (qwen3)


class Transcriber(Protocol):
    name: str
    model: str

    def transcribe(self, wav: Path) -> list[Word]:
        """Mots horodatés de `wav` (mono 16 kHz)."""
        ...


def words_from_tokens(
    tokens: list[str], times: list[float], logprobs: list[float] | None, offset: float, segment_end: float
) -> list[Word]:
    """Regroupe des tokens SentencePiece (« ▁Écoute », « ' moi » → espace initiale = nouveau mot) en mots horodatés."""
    groups: list[tuple[str, float, float, list[float]]] = []  # texte, début, dernier token, logprobs
    for i, token in enumerate(tokens):
        t = offset + times[i]
        lp = logprobs[i] if logprobs else 0.0
        starts_word = token.startswith((" ", "▁")) or not groups
        clean = token.lstrip(" ▁")
        if starts_word:
            groups.append((clean, t, t, [lp]))
        else:
            text, start, _, lps = groups[-1]
            groups[-1] = (text + clean, start, t, [*lps, lp])
    words: list[Word] = []
    for i, (text, start, last, lps) in enumerate(groups):
        next_start = groups[i + 1][1] if i + 1 < len(groups) else segment_end
        end = min(next_start, last + WORD_TAIL, max(segment_end, last))
        if text.strip():
            words.append(
                Word(text, round(start, 3), round(max(end, start + 0.01), 3), round(math.exp(sum(lps) / len(lps)), 3))
            )
    return merge_punctuation(words)


def merge_punctuation(words: list[Word]) -> list[Word]:
    """Un « mot » qui n'est que de la ponctuation (« ? », « . ») est collé au mot précédent."""
    merged: list[Word] = []
    for w in words:
        if merged and re.fullmatch(r"\W+", w.text):
            prev = merged[-1]
            merged[-1] = Word(prev.text + w.text, prev.start, max(prev.end, w.end), prev.confidence)
        else:
            merged.append(w)
    return merged


def normalize_words(text: str) -> list[str]:
    """Pour comparer deux transcriptions : minuscules, sans ponctuation, apostrophes unifiées."""
    text = text.lower().replace("’", "'")
    return re.findall(r"[\w']+", text)


def word_error_rate(reference: str, hypothesis: str) -> float:
    """WER (distance d'édition au mot / nb de mots de la référence)."""
    ref, hyp = normalize_words(reference), normalize_words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        current = [i]
        for j, h in enumerate(hyp, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (r != h)))
        previous = current
    return previous[-1] / len(ref)


MIN_WORD = 0.05  # durée minimale d'un mot après répartition (s)


def fix_overlaps(words: list[Word]) -> list[Word]:
    """Aucun chevauchement entre mots consécutifs.

    1. Mots émis au même instant (Parakeet sort parfois « c'est un peu » dans la même trame) : on répartit
       équitablement la durée du groupe entre eux.
    2. Un mot finit au plus tard quand le suivant commence (jonctions de segments VAD, ponctuation collée).
    """
    fixed = list(words)
    i = 0
    while i < len(fixed):
        j = i
        while j + 1 < len(fixed) and fixed[j + 1].start <= fixed[i].start + 1e-6:
            j += 1
        if j > i:
            count = j - i + 1
            base = fixed[i].start
            end = max(w.end for w in fixed[i : j + 1])
            if j + 1 < len(fixed):
                end = min(end, fixed[j + 1].start)
            step = max((end - base) / count, MIN_WORD)
            for k in range(i, j + 1):
                w = fixed[k]
                start = base + step * (k - i)
                fixed[k] = Word(w.text, round(start, 3), round(start + step, 3), w.confidence)
        i = j + 1
    for i in range(len(fixed) - 1):
        nxt = fixed[i + 1].start
        if fixed[i].end > nxt:
            w = fixed[i]
            fixed[i] = Word(w.text, w.start, max(nxt, w.start), w.confidence)
    return fixed
