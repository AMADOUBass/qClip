"""Chaîne complète d'une VOD (SPEC §4) : scout → fetch → ingest → transcribe → candidates.

Utilisée par `qclip process` et par l'interface (bouton « Analyser »). Chaque étape réutilise ce qui existe déjà.
"""

from qclip.campaign import check_source, load_campaign
from qclip.candidates import build_candidates
from qclip.config import cpu_threads, load_config
from qclip.fetch import fetch_windows
from qclip.ingest import ingest_windows
from qclip.scout import scout_source
from qclip.steps import Steps
from qclip.transcribe import transcribe_windows

STAGES = ["repérage", "téléchargement", "séparation", "transcription", "détection"]


def process_vod(slug: str, url: str, steps: Steps, force: bool = False) -> str:
    """Traite une source de la campagne jusqu'aux candidats. Renvoie le video_id."""
    config, brief = load_config(), load_campaign(slug)
    check_source(brief, slug, url)
    steps.stage("repérage")
    scout = scout_source(slug, url, steps, force=force)
    vid = scout["video_id"]
    steps.stage("téléchargement")
    fetch_windows(slug, scout, steps, force=force)
    steps.stage("séparation")
    ingest_windows(vid, steps, config.separation.enabled, config.separation.model, force=force)
    steps.stage("transcription")
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
    build_candidates(slug, vid, steps, force=force)
    return vid
