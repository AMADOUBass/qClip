"""Briefs de campagne (campaigns/<slug>.yaml) : modèle pydantic, chargement et création depuis le modèle."""

import re
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, field_validator

from qclip import ROOT
from qclip.config import ClipBounds, ConfigError, StrictModel, format_validation_error, read_yaml

CAMPAIGNS_DIR = ROOT / "campaigns"
TEMPLATE_NAME = "_template.yaml"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class Required(StrictModel):
    mention: str = ""
    hashtags: list[str] = []
    caption_note: str = ""

    @field_validator("mention")
    @classmethod
    def check_mention(cls, value: str) -> str:
        if value and (not value.startswith("@") or " " in value):
            raise ValueError("la mention doit commencer par @ et ne pas contenir d'espace (ex. @streamerx)")
        return value

    @field_validator("hashtags")
    @classmethod
    def check_hashtags(cls, values: list[str]) -> list[str]:
        for tag in values:
            if not tag.startswith("#") or len(tag) < 2 or " " in tag:
                raise ValueError(f"hashtag invalide {tag!r} : il doit commencer par # et ne pas contenir d'espace")
        return values


class Brief(StrictModel):
    name: str = Field(min_length=1)
    creator: str = Field(min_length=1)
    platforms: list[Literal["tiktok", "shorts", "reels"]] = Field(min_length=1)
    rate_per_1k: float = Field(ge=0)
    sources: list[str] = []
    clip: ClipBounds
    required: Required = Required()
    forbidden: list[str] = []
    layout: Literal["facecam", "blur", "crop"]
    language: str = Field(default="fr", pattern=r"^[a-z]{2}$")
    # Campagne de test (VOD non autorisée par une vraie campagne) : traitement local permis,
    # mais aucun clip « prêt à poster » ne doit en sortir (bloqué au rendu final / meta, M4-M5).
    test_only: bool = False
    # Zone webcam fixée à la main [x, y, largeur, hauteur] en pixels de la source (sinon détectée par YuNet).
    facecam: list[int] | None = None

    @field_validator("facecam")
    @classmethod
    def check_facecam(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and (len(value) != 4 or value[2] <= 0 or value[3] <= 0 or min(value[:2]) < 0):
            raise ValueError("facecam attend [x, y, largeur, hauteur] en pixels, ex. [1500, 40, 380, 280]")
        return value

    @field_validator("sources")
    @classmethod
    def check_sources(cls, values: list[str]) -> list[str]:
        for url in values:
            if not url.startswith(("https://", "http://")):
                raise ValueError(f"source invalide {url!r} : une URL http(s) est attendue")
        return values


def load_brief(path: Path) -> Brief:
    data = read_yaml(path)
    try:
        return Brief.model_validate(data)
    except ValidationError as e:
        raise ConfigError(format_validation_error(path.name, e)) from e


def load_campaign(slug: str, campaigns_dir: Path = CAMPAIGNS_DIR) -> Brief:
    path = campaigns_dir / f"{slug}.yaml"
    if not path.exists():
        raise ConfigError(f"campagne {slug!r} introuvable : crée-la avec `qclip campaign new {slug}`")
    return load_brief(path)


def check_source(brief: Brief, slug: str, url: str) -> None:
    """Règle absolue : on ne traite qu'une URL listée dans le brief de la campagne."""
    if url not in brief.sources:
        raise ConfigError(
            f"{url} n'est pas dans les sources de la campagne {slug!r} : ajoute-la dans campaigns/{slug}.yaml"
        )


def brief_paths(campaigns_dir: Path = CAMPAIGNS_DIR) -> list[Path]:
    """Tous les briefs, modèle compris (il doit rester valide lui aussi)."""
    return sorted(campaigns_dir.glob("*.yaml"))


def new_campaign(slug: str, campaigns_dir: Path = CAMPAIGNS_DIR) -> Path:
    """Crée campaigns/<slug>.yaml à partir du modèle et renvoie son chemin."""
    if not SLUG_RE.match(slug):
        raise ConfigError(
            f"slug invalide {slug!r} : minuscules, chiffres et tirets seulement, "
            "sans tiret au début (ex. streamerx-gta6)"
        )
    template = campaigns_dir / TEMPLATE_NAME
    target = campaigns_dir / f"{slug}.yaml"
    if target.exists():
        raise ConfigError(f"la campagne {slug!r} existe déjà : {target}")
    load_brief(template)  # on ne copie jamais un modèle cassé
    target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    return target
