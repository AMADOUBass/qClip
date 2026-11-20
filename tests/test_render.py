from pathlib import Path

import pytest

from qclip.config import load_config
from qclip.facecam import Facecam, classify, rect_around_face
from qclip.render import choose_layout, save_words_tsv
from qclip.subtitles import SAFE_BOTTOM, TimedWord, build_ass, group_lines, override_color


def tw(text: str, start: float, dur: float = 0.3) -> TimedWord:
    return TimedWord(text, start, start + dur)


def test_group_lines_breaks_on_count_sentence_comma_and_pause() -> None:
    words = [tw("Vas-y,", 0), tw("viens", 0.3), tw("on", 0.6), tw("y", 0.9), tw("va!", 1.2), tw("Voilà", 3.0)]
    lines = [[w.text for w in line] for line in group_lines(words, 3)]
    assert lines == [["Vas-y,", "viens", "on"], ["y", "va!"], ["Voilà"]]
    words = [tw("bon", 0), tw("ok,", 0.3), tw("alors", 0.6), tw("on", 0.9)]
    assert [[w.text for w in line] for line in group_lines(words, 3)] == [["bon", "ok,"], ["alors", "on"]]


def test_override_color_is_bgr() -> None:
    assert override_color("#FFD400") == "&H00D4FF&"


def test_build_ass_highlights_each_word_in_turn() -> None:
    style = load_config().subtitle
    words = [tw("t'es", 0.0), tw("chaud", 0.3), tw("toi?", 0.6)]
    subs = build_ass(words, style, center_y=1400, clip_duration=5.0, hook="Accroche", mention="@x", watermark="TEST")
    events = [e for e in subs if e.style == "Words"]
    assert len(events) == 3
    assert [(e.start, e.end) for e in events] == [(0, 300), (300, 600), (600, 1300)]  # dernier mot (fin 0,9 s) + 0,4 s
    assert "\\c&H00D4FF&}CHAUD" in events[1].text and "\\pos(540,1400)" in events[1].text
    hook = next(e for e in subs if e.style == "Hook")
    assert (hook.start, hook.end) == (0, 3000) and "ACCROCHE" in hook.text
    assert SAFE_BOTTOM > 1400


def test_words_tsv_is_generated_output(tmp_path: Path) -> None:
    path = tmp_path / "clip_1.words.tsv"
    save_words_tsv([tw("salut", 0.15), tw("toi.", 0.5)], path, (7659.0, 7687.0))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("# passage 7659.000 7687.000") and "GÉNÉRÉ" in lines[1]
    assert lines[2:] == ["0.150\t0.450\tsalut", "0.500\t0.800\ttoi."]


def test_facecam_classification_on_real_detections() -> None:
    # Détections réelles (YuNet, 1920x1080) sur 3 images de clips de la VOD de test.
    fullcam = [  # caméra plein cadre + poster de Messi + tableau du gorille (immobiles)
        [[841, 570, 234, 319], [1335, 353, 40, 46], [205, 401, 83, 97]],
        [[827, 506, 231, 334], [1335, 355, 40, 47]],
        [[838, 492, 210, 312], [1335, 354, 41, 47], [208, 422, 79, 93]],
    ]
    match = [  # match de foot : arbitre au centre (146 px, immobile) + webcam en haut à droite (bouge)
        [[825, 310, 146, 204], [1665, 147, 52, 52]],
        [[825, 311, 146, 204], [1665, 114, 47, 57]],
        [[825, 310, 146, 204], [1668, 123, 51, 64]],
    ]
    standing = [  # le streamer se lève : son visage n'est vu qu'une fois, le poster reste
        [[880, 497, 245, 316], [1330, 362, 40, 47]],
        [[1331, 361, 40, 47]],
        [[1329, 363, 41, 46]],
    ]
    to_float = lambda frames: [[[float(v) for v in f] for f in faces] for faces in frames]  # noqa: E731
    assert classify(to_float(fullcam), 1920, 1080).mode == "fullcam"
    cam = classify(to_float(match), 1920, 1080)
    assert cam.mode == "overlay" and cam.rect is not None
    x, y, w, h = cam.rect
    assert x >= 1443 and x + w <= 1920 and y + h <= 300  # dans la vraie webcam (x 1443-1920, y 0-268 environ)
    assert w / h == pytest.approx(1080 / 640, rel=0.01)
    assert classify(to_float(standing), 1920, 1080).mode == "fullcam"  # pas le poster
    assert classify([[], [], []], 1920, 1080).mode == "none"
    assert rect_around_face([10.0, 10.0, 50.0, 60.0], 1920, 1080)[0] == 0  # collé au bord : reste dans l'image


def test_choose_layout_falls_back_to_blur() -> None:
    layout, warning = choose_layout("facecam", Facecam("fullcam", [800, 500, 230, 270], None, "yunet"), 30, 1920, 1080)
    assert layout.name == "blur" and warning and "plein cadre" in warning
    layout, warning = choose_layout("facecam", Facecam("overlay", None, [1500, 40, 380, 225], "brief"), 30, 1920, 1080)
    assert layout.name == "facecam" and warning is None
    assert 640 < layout.subs_y < SAFE_BOTTOM  # sous la webcam, au-dessus de la zone interdite
    assert "vstack" in layout.filter
