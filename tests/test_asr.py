import math

import pytest

from qclip.asr.base import (
    Word,
    fix_overlaps,
    merge_punctuation,
    normalize_words,
    word_error_rate,
    words_from_tokens,
)
from qclip.asr.qwen3 import attach_punctuation


def test_words_from_tokens_groups_subwords() -> None:
    # Sortie réelle de Parakeet (onnx-asr) : espace initiale = début de mot, temps relatifs au segment VAD.
    tokens = [" T", "'", "as", " vu", " d", "'", "un", " fre", "eze", "?"]
    times = [0.0, 0.08, 0.08, 0.16, 0.32, 0.32, 0.4, 0.48, 0.56, 0.64]
    logprobs = [math.log(0.9)] * len(tokens)
    words = words_from_tokens(tokens, times, logprobs, offset=3.39, segment_end=4.13)
    assert [w.text for w in words] == ["T'as", "vu", "d'un", "freeze?"]
    assert words[0].start == pytest.approx(3.39)
    assert words[1].start == pytest.approx(3.55)
    assert words[-1].end == pytest.approx(4.13)
    for a, b in zip(words, words[1:], strict=False):
        assert a.end <= b.start + 1e-9
    assert words[0].confidence == pytest.approx(0.9, abs=1e-3)


def test_word_end_capped_during_silence() -> None:
    # « oui » puis 3 s de silence avant « non » : « oui » ne doit pas durer 3 s.
    words = words_from_tokens([" oui", " non"], [0.0, 3.0], None, offset=10.0, segment_end=13.5)
    assert words[0].end == pytest.approx(10.4)
    assert words[1].start == pytest.approx(13.0)


def test_merge_punctuation() -> None:
    words = merge_punctuation([Word("Quoi", 0.0, 0.3, 0.9), Word("?", 0.3, 0.4, 0.5), Word("Rien", 0.5, 0.8, 0.8)])
    assert [w.text for w in words] == ["Quoi?", "Rien"]
    assert words[0].end == 0.4


def test_attach_punctuation() -> None:
    words = [Word("écoute", 0, 1, None), Word("moi", 1, 2, None), Word("bien", 2, 3, None)]
    out = attach_punctuation(words, "Écoute-moi, bien.")
    assert [w.text for w in out] == ["Écoute", "moi,", "bien."]
    assert [(w.start, w.end) for w in out] == [(0, 1), (1, 2), (2, 3)]


def test_normalize_words() -> None:
    assert normalize_words("C’est PAS possible, wesh!") == ["c'est", "pas", "possible", "wesh"]


@pytest.mark.parametrize(
    ("ref", "hyp", "wer"),
    [
        ("t'as vu le freeze", "t'as vu le freeze", 0.0),
        ("t'as vu le freeze", "T'as vu le freeze ?", 0.0),
        ("t'as vu le freeze", "t'as vu la frise", 0.5),
        ("un deux trois quatre", "un trois quatre", 0.25),
        ("", "", 0.0),
    ],
)
def test_word_error_rate(ref: str, hyp: str, wer: float) -> None:
    assert word_error_rate(ref, hyp) == pytest.approx(wer)


def test_fix_overlaps() -> None:
    words = fix_overlaps([Word("a", 0.0, 1.5, 1.0), Word("b", 1.0, 2.0, 1.0), Word("c", 2.0, 2.5, 1.0)])
    assert [(w.start, w.end) for w in words] == [(0.0, 1.0), (1.0, 2.0), (2.0, 2.5)]


def test_fix_overlaps_spreads_same_start_words() -> None:
    # Cas réel (w_02) : « c'est », « un », « peu... » émis à 8436.299 ; le groupe finit à 8437.499.
    words = fix_overlaps(
        [
            Word("c'est", 8436.299, 8436.309, 0.9),
            Word("un", 8436.299, 8436.309, 0.9),
            Word("peu...", 8436.299, 8437.499, 0.9),
            Word("après", 8438.0, 8438.3, 0.9),
        ]
    )
    assert [w.text for w in words] == ["c'est", "un", "peu...", "après"]
    assert [w.start for w in words] == pytest.approx([8436.299, 8436.699, 8437.099, 8438.0])
    for a, b in zip(words, words[1:], strict=False):
        assert a.end <= b.start + 1e-9
        assert a.end > a.start
