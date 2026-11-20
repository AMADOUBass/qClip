"""Chaîne complète d'une VOD (SPEC §4) : scout → fetch → ingest → transcribe → candidates.

Utilisée par `qclip process` et par l'interface (bouton « Analyser »). Chaque étape réutilise ce qui existe déjà.
La durée de chaque grande étape est gardée dans work/<id>/timings.json (écran VOD, estimations des suivantes).
"""

import json
from pathlib import Path

from qclip.campaign import check_source, load_campaign
from qclip.candidates import build_candidates
from qclip.config import cpu_threads, load_config
from qclip.fetch import fetch_windows
from qclip.ingest import ingest_windows
from qclip.scout import scout_source
from qclip.sources import WORK_DIR
from qclip.steps import Steps, merge_timings
from qclip.transcribe import transcribe_windows

STAGES = ["repérage", "téléchargement", "séparation", "transcription", "détection"]


def timings_path(vid: str) -> Path:
    return WORK_DIR / vid / "timings.json"


REAL_ZONE_S = 2.0  # une zone vraiment traitée (téléchargée, transcrite…) prend plus ; en dessous, c'est le cache


def save_stage_times(vid: str, steps: Steps, windows: int) -> None:
    """Ajoute les grandes étapes terminées à timings.json (sans écraser une vraie mesure par une reprise du cache).

    `per_zone` : secondes de chaque zone réellement traitée, pour estimer les étapes des prochaines VOD.
    """
    path = timings_path(vid)
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    per_zone = dict(old.get("per_zone", {}))
    for stage, zones in steps.zone_times.items():
        real = [round(s, 1) for s in zones.values() if s >= REAL_ZONE_S]
        if real:
            per_zone[stage] = real
    data = {"windows": windows, "stages": merge_timings(old.get("stages", {}), steps.stage_times), "per_zone": per_zone}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def process_vod(slug: str, url: str, steps: Steps, force: bool = False) -> str:
    """Traite une source de la campagne jusqu'aux candidats. Renvoie le video_id."""
    config, brief = load_config(), load_campaign(slug)
    check_source(brief, slug, url)
    steps.stage("repérage")
    scout = scout_source(slug, url, steps, force=force)
    vid, windows = scout["video_id"], len(scout["windows"])
    steps.stage("téléchargement")
    fetch_windows(slug, scout, steps, force=force)
    steps.stage("séparation")
    save_stage_times(vid, steps, windows)
    ingest_windows(vid, steps, config.separation.enabled, config.separation.model, force=force)
    steps.stage("transcription")
    save_stage_times(vid, steps, windows)
    transcribe_windows(
        vid,
        steps,
        backend=config.asr.backend,
        model=config.asr.model,
        quantization=config.asr.quantization,
        language=brief.language,
        threads=cpu_threads(config),
        prompt=brief.creator,
        force=force,
    )
    steps.stage("détection")
    save_stage_times(vid, steps, windows)
    build_candidates(slug, vid, steps, force=force)
    steps.end_stage()
    save_stage_times(vid, steps, windows)
    return vid
