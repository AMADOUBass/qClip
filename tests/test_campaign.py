import shutil
from pathlib import Path

import pytest

from qclip.campaign import CAMPAIGNS_DIR, TEMPLATE_NAME, load_brief, new_campaign
from qclip.config import ConfigError

TEMPLATE = CAMPAIGNS_DIR / TEMPLATE_NAME

VALID_BRIEF = """
name: "Test — clips GTA 6"
creator: "Test"
platforms: [tiktok]
rate_per_1k: 0.5
sources: ["https://www.twitch.tv/videos/1"]
clip: { min_len: 20, max_len: 45 }
required: { mention: "@test", hashtags: ["#gta6"] }
layout: blur
"""

INVALID_BRIEF = """
name: "Test"
creator: "Test"
platforms: [tiktok, myspace]
rate_per_1k: -1
sources: ["www.twitch.tv/videos/1"]
clip: { min_len: 20, max_len: 45 }
required: { mention: "test", hashtags: ["gta6"] }
layout: vertical
langue: fr
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "brief.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_template_is_valid() -> None:
    brief = load_brief(TEMPLATE)
    assert brief.layout == "facecam"
    assert brief.required.hashtags == ["#streamerx", "#gta6"]


def test_valid_brief(tmp_path: Path) -> None:
    brief = load_brief(write(tmp_path, VALID_BRIEF))
    assert brief.platforms == ["tiktok"]
    assert brief.clip.max_len == 45
    assert brief.language == "fr"  # valeur par défaut
    assert brief.forbidden == []


def test_invalid_brief_reports_every_field(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_brief(write(tmp_path, INVALID_BRIEF))
    message = str(exc.value)
    for field in ["platforms.1", "rate_per_1k", "sources", "required.mention", "required.hashtags", "layout"]:
        assert f"  - {field} :" in message
    assert "langue : champ inconnu" in message


def test_missing_field(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="creator : champ obligatoire manquant"):
        load_brief(write(tmp_path, VALID_BRIEF.replace('creator: "Test"\n', "")))


def test_new_campaign(tmp_path: Path) -> None:
    shutil.copy(TEMPLATE, tmp_path / TEMPLATE_NAME)
    path = new_campaign("streamerx-gta6", tmp_path)
    assert path == tmp_path / "streamerx-gta6.yaml"
    assert load_brief(path).name == load_brief(TEMPLATE).name
    with pytest.raises(ConfigError, match="existe déjà"):
        new_campaign("streamerx-gta6", tmp_path)


@pytest.mark.parametrize("slug", ["StreamerX", "_template", "-x", "a b", "a/b", ""])
def test_new_campaign_rejects_bad_slug(tmp_path: Path, slug: str) -> None:
    with pytest.raises(ConfigError, match="slug invalide"):
        new_campaign(slug, tmp_path)
