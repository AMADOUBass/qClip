from pathlib import Path

import pytest

from qclip import edits
from qclip.campaign import CAMPAIGNS_DIR, TEMPLATE_NAME, load_brief, save_brief
from qclip.config import ConfigError, load_config
from qclip.subtitles import TimedWord, build_ass

WORDS = [
    {"text": "Il", "start": 100.0, "end": 100.2},
    {"text": "a", "start": 100.2, "end": 100.3},
    {"text": "commandé", "start": 100.3, "end": 100.8},
    {"text": "un", "start": 100.8, "end": 100.9},
    {"text": "omard", "start": 100.9, "end": 101.4},
    {"text": "omard?", "start": 105.0, "end": 105.5},
]


@pytest.fixture(autouse=True)
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(edits, "WORK_DIR", tmp_path)
    (tmp_path / "twitch-1").mkdir()
    return tmp_path


def test_save_edit_validates_and_clears() -> None:
    assert edits.save_edit("twitch-1", 7, decision="keep", style="karaoke") == {"decision": "keep", "style": "karaoke"}
    assert edits.load_edits("twitch-1")[7]["decision"] == "keep"
    edits.save_edit("twitch-1", 7, style=None)  # None = retour au défaut
    assert edits.load_edits("twitch-1")[7] == {"decision": "keep"}
    edits.save_edit("twitch-1", 7, decision=None)
    assert 7 not in edits.load_edits("twitch-1")
    with pytest.raises(ValueError, match="decision invalide"):
        edits.save_edit("twitch-1", 7, decision="maybe")
    with pytest.raises(ValueError, match="réglage inconnu"):
        edits.save_edit("twitch-1", 7, color="red")


def test_snap_bounds_never_cuts_a_word() -> None:
    start, end = edits.snap_bounds(100.5, 101.1, WORDS, (95.0, 180.0))  # au milieu de « commandé » et « omard »
    assert start == pytest.approx(100.15) and end == pytest.approx(101.55)
    with pytest.raises(ValueError, match="trop court"):
        edits.snap_bounds(100.0, 100.5, [], (95.0, 180.0))
    assert edits.snap_bounds(90.0, 200.0, WORDS, (95.0, 180.0)) == (95.0, 180.0)  # gardé dans la plage


def test_apply_edit_recomputes_text_and_file_position() -> None:
    c = {"start": 99.0, "end": 130.0, "file_start": 4.0, "duration": 31.0, "peak": 110.0, "text": "…"}
    out = edits.apply_edit(c, {"start": 100.5}, WORDS, window_end=180.0)
    assert out["start"] == pytest.approx(100.15) and out["file_start"] == pytest.approx(5.15)
    assert out["text"].startswith("a commandé") and out["edited"]
    assert edits.apply_edit(c, {"style": "box"}, WORDS, 180.0) is c  # pas de bornes : inchangé


def test_correct_everywhere_keeps_punctuation() -> None:
    fixes = edits.correct_everywhere(WORDS, "omard", "homard")
    assert fixes == {"100.900": "homard", "105.000": "homard?"}
    fixed = edits.corrected(WORDS, fixes)
    assert [w["text"] for w in fixed][-2:] == ["homard", "homard?"]


@pytest.mark.parametrize(("variant", "marker"), [("neon", r"\c&H00D4FF&"), ("box", r"\bord18"),
                                                 ("outline", r"\fscx108"), ("karaoke", r"\kf")])  # fmt: skip
def test_subtitle_styles(variant: str, marker: str) -> None:
    words = [TimedWord("il", 0.0, 0.3), TimedWord("a", 0.3, 0.5), TimedWord("vu", 0.5, 0.9)]
    subs = build_ass(words, load_config().subtitle, center_y=1400, clip_duration=5.0, variant=variant)
    texts = [e.text for e in subs]
    assert any(marker in t for t in texts)
    assert all(ord(ch) >= 32 for t in texts for ch in t)  # aucun caractère de contrôle (bug des \b et \3c)
    if variant == "karaoke":
        assert len(texts) == 1 and r"\kf30" in texts[0]  # une seule ligne qui se remplit, 0,3 s par mot


def test_save_brief_roundtrip(tmp_path: Path) -> None:
    data = load_brief(CAMPAIGNS_DIR / TEMPLATE_NAME).model_dump(mode="json")
    data |= {"budget_total": 2000, "payout_min": 5, "payout_max": 75, "source_platform": "kick",
             "overlay": {"file": "overlay-kick.png", "x": 0.7, "y": 0.3, "width": 0.2},
             "requirements": {"link_in_bio": "Risor Tracker", "dedicated_account": True}}  # fmt: skip
    (tmp_path / "bichou.yaml").write_text("", encoding="utf-8")
    brief = save_brief("bichou", data, tmp_path)
    again = load_brief(tmp_path / "bichou.yaml")
    assert again == brief and again.overlay is not None and again.overlay.file == "overlay-kick.png"
    with pytest.raises(ConfigError, match="existe déjà"):
        save_brief("bichou", data, tmp_path, create=True)
    with pytest.raises(ConfigError, match="budget_total"):
        save_brief("bichou", {**data, "budget_total": -5}, tmp_path)
