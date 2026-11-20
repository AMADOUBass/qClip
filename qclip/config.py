"""Config globale (config.yaml) : modèles pydantic, chargement YAML et messages d'erreur lisibles."""

from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from qclip import ROOT

CONFIG_PATH = ROOT / "config.yaml"


class ConfigError(Exception):
    """Fichier YAML illisible ou invalide. Le message est prêt à afficher."""


class StrictModel(BaseModel):
    # Une clé inconnue est une erreur : une faute de frappe dans un brief ne doit pas passer en silence.
    model_config = ConfigDict(extra="forbid")


class ClipBounds(StrictModel):
    min_len: float = Field(gt=0)
    max_len: float = Field(gt=0)

    @model_validator(mode="after")
    def check_order(self) -> Self:
        if self.min_len >= self.max_len:
            raise ValueError(f"min_len ({self.min_len}) doit être plus petit que max_len ({self.max_len})")
        return self


class ClipsConfig(ClipBounds):
    top_n: int = Field(ge=1)
    preroll: float = Field(ge=0)
    target_len: float | None = Field(default=None, gt=0)  # durée visée ; bornée par min_len / max_len du brief


class AsrConfig(StrictModel):
    backend: Literal["parakeet", "whisper", "qwen3"]
    model: str = Field(min_length=1)
    quantization: str = Field(min_length=1)


class SeparationConfig(StrictModel):
    enabled: bool
    model: str


class ScoutConfig(StrictModel):
    window_len: float = Field(gt=0)
    windows_factor: int = Field(ge=1)
    chat_delay: float = Field(ge=0)
    emote_bonus: float = Field(ge=0)  # un message avec emote de rire / choc compte 1 + emote_bonus


class WeightsConfig(StrictModel):
    chat: float = Field(ge=0)
    loudness: float = Field(ge=0)
    audio_events: float = Field(ge=0)
    speech_energy: float = Field(ge=0)


class FeaturesConfig(StrictModel):
    clap: bool
    scenes: bool


class LlmConfig(StrictModel):
    use_llm: bool
    use_vision: bool
    text_model: str
    vision_model: str


class RenderConfig(StrictModel):
    layout: Literal["facecam", "blur", "crop"]
    fps: int = Field(gt=0, le=120)
    encoder: Literal["auto", "h264_qsv", "libx264"]
    lufs: float = Field(le=0)


class SubtitleConfig(StrictModel):
    font: str = Field(min_length=1)
    size: int = Field(gt=0)
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    highlight: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    outline: float = Field(ge=0)
    words_per_line: int = Field(ge=1, le=6)
    uppercase: bool
    style: Literal["neon", "box", "outline", "karaoke"] = "neon"  # mot prononcé : couleur / bloc / contour / karaoké


class Config(StrictModel):
    device: Literal["auto", "cpu", "cuda"]
    threads: Literal["auto"] | int = Field(union_mode="left_to_right")
    asr: AsrConfig
    separation: SeparationConfig
    scout: ScoutConfig
    clips: ClipsConfig
    weights: WeightsConfig
    chat_emotes: list[str]
    chat_bots: list[str]  # logins ignorés dans le chat (minuscules)
    audio_event_labels: list[str]
    keywords: list[str]
    features: FeaturesConfig
    llm: LlmConfig
    render: RenderConfig
    subtitle: SubtitleConfig


def read_yaml(path: Path) -> dict[str, Any]:
    """Lit un fichier YAML dont la racine doit être un dictionnaire."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"{path.name} : fichier introuvable ({path})") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"{path.name} : YAML invalide\n  {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} : le fichier doit contenir des paires « clé: valeur »")
    return data


def format_validation_error(source: str, error: ValidationError) -> str:
    """Une ligne par champ fautif : `clip.min_len : Input should be greater than 0 (reçu : -5)`."""
    lines = [f"{source} : {error.error_count()} champ(s) invalide(s)"]
    for err in error.errors():
        field = ".".join(str(part) for part in err["loc"]) or "(racine)"
        if err["type"] == "missing":
            lines.append(f"  - {field} : champ obligatoire manquant")
        elif err["type"] == "extra_forbidden":
            lines.append(f"  - {field} : champ inconnu (faute de frappe ?)")
        else:
            msg = err["msg"].removeprefix("Value error, ")  # nos propres messages, déjà en français
            lines.append(f"  - {field} : {msg} (reçu : {err['input']!r})")
    return "\n".join(lines)


def load_config(path: Path = CONFIG_PATH) -> Config:
    data = read_yaml(path)
    try:
        return Config.model_validate(data)
    except ValidationError as e:
        raise ConfigError(format_validation_error(path.name, e)) from e


def cpu_threads(config: Config) -> int:
    """`threads: auto` → nombre de cœurs physiques (les cœurs logiques n'aident pas l'inférence ONNX / CTranslate2)."""
    if config.threads != "auto":
        return int(config.threads)
    import psutil

    return psutil.cpu_count(logical=False) or 4
