import json
from pathlib import Path

import numpy as np
import pytest

from qclip.campaign import CAMPAIGNS_DIR, TEMPLATE_NAME, check_source, load_brief
from qclip.chat import ChatMessage, is_noise, is_reaction, load_chat
from qclip.config import ConfigError
from qclip.sources import safe_id, twitch_vod_id
from qclip.utils.audio import find_offset


@pytest.mark.parametrize(
    ("url", "vod"),
    [
        ("https://www.twitch.tv/videos/2612345678", "2612345678"),
        ("https://twitch.tv/videos/123?t=1h2m3s", "123"),
        ("https://www.twitch.tv/somestreamer/video/987", "987"),
        ("https://www.youtube.com/watch?v=abc", None),
    ],
)
def test_twitch_vod_id(url: str, vod: str | None) -> None:
    assert twitch_vod_id(url) == vod


def test_safe_id() -> None:
    assert safe_id("Youtube-AbC:12/x") == "Youtube-AbC_12_x"


def test_check_source_requires_url_in_brief() -> None:
    brief = load_brief(CAMPAIGNS_DIR / TEMPLATE_NAME)
    check_source(brief, "x", "https://www.twitch.tv/videos/123456789")
    with pytest.raises(ConfigError, match="n'est pas dans les sources"):
        check_source(brief, "x", "https://www.twitch.tv/videos/999")


def test_load_chat(tmp_path: Path) -> None:
    data = {
        "video": {"id": "1", "length": 100.0},
        "comments": [
            {"content_offset_seconds": 12.5, "message": {"body": "OMEGALUL", "fragments": []}},
            {"content_offset_seconds": 3.0, "message": {"body": "salut", "fragments": []}},
        ],
    }
    path = tmp_path / "chat.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    messages = load_chat(path)
    assert [(m.offset, m.text) for m in messages] == [(3.0, "salut"), (12.5, "OMEGALUL")]


def test_is_reaction() -> None:
    emotes = ["KEKW", "W", "💀"]
    assert is_reaction("KEKW KEKW", emotes)
    assert is_reaction("c'est mort 💀", emotes)
    assert not is_reaction("Wesh la team", emotes)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Wshhhhhhhhhhhh ahahahha", True),
        ("MDRRRR", True),
        ("mdrr t'es fou", True),
        ("LUL,", True),
        ("Roi de la touche 🤣🤣🤣", True),
        ("Wowww", False),
        ("w", True),
        ("on regarde le match", False),
    ],
)
def test_is_reaction_french_chat(text: str, expected: bool) -> None:
    emotes = ["LUL", "W", "🤣", "mdr", "wsh", "ahah"]
    assert is_reaction(text, emotes) is expected


def test_is_noise() -> None:
    assert is_noise(ChatMessage(1.0, "Le discord du gang -> …", "wizebot"), ["wizebot"])
    assert is_noise(ChatMessage(1.0, " !discord", "viewer"), ["wizebot"])
    assert not is_noise(ChatMessage(1.0, "wshhh", "viewer"), ["wizebot"])


def test_find_offset_recovers_shift() -> None:
    rng = np.random.default_rng(0)
    reference = rng.normal(0, 0.1, 8000 * 40).astype(np.float32)
    probe = reference[8000 * 13 + 1234 : 8000 * 33 + 1234]
    lag, quality = find_offset(reference, probe)
    assert lag == 8000 * 13 + 1234
    assert quality > 0.99
