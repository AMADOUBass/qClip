from pathlib import Path

import pytest

from qclip.config import CONFIG_PATH, ConfigError, load_config


def test_project_config_loads() -> None:
    config = load_config(CONFIG_PATH)
    assert config.device == "auto"
    assert config.threads == "auto"
    assert config.asr.backend == "parakeet"
    assert config.clips.min_len == 15 and config.clips.max_len == 59
    assert config.render.encoder == "auto"
    assert "KEKW" in config.chat_emotes


def write_config(tmp_path: Path, old: str, new: str) -> Path:
    text = CONFIG_PATH.read_text(encoding="utf-8")
    assert old in text
    path = tmp_path / "config.yaml"
    path.write_text(text.replace(old, new), encoding="utf-8")
    return path


def test_invalid_config_lists_bad_fields(tmp_path: Path) -> None:
    path = write_config(tmp_path, "min_len: 15, max_len: 59", "min_len: 80, max_len: 59")
    with pytest.raises(ConfigError, match=r"clips : .*min_len \(80\.0\) doit être plus petit"):
        load_config(path)


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    path = write_config(tmp_path, "device: auto", "device: auto\ndevise: cpu")
    with pytest.raises(ConfigError, match="devise : champ inconnu"):
        load_config(path)


def test_threads_accepts_int(tmp_path: Path) -> None:
    path = write_config(tmp_path, "threads: auto", "threads: 4")
    assert load_config(path).threads == 4


def test_broken_yaml(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("device: [auto\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML invalide"):
        load_config(path)
