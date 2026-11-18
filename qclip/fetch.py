"""Téléchargement des seules plages vidéo repérées par le scout (SPEC §4.2)."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from qclip.campaign import check_source, load_campaign
from qclip.sources import WORK_DIR, download_section, find_output, record_source
from qclip.steps import Steps
from qclip.utils.audio import find_offset, read_pcm
from qclip.utils.ffmpeg import ffprobe

MARGIN = 5.0  # secondes ajoutées de chaque côté de la fenêtre
SYNC_SR = 8000
SYNC_PROBE = 20.0  # secondes du début de la plage comparées à l'audio du scout
SYNC_SEARCH = 10.0  # on cherche le vrai début à ± 10 s du début demandé
SYNC_MIN_QUALITY = 0.5


@dataclass
class FetchedWindow:
    rank: int
    file: str
    requested_start: float
    requested_end: float
    start: float  # vrai début dans la VOD (recalé sur l'audio), en secondes
    duration: float
    sync_quality: float  # corrélation 0-1 ; sous SYNC_MIN_QUALITY, `start` = début demandé


def real_start(scout_audio: Path, clip: Path, requested: float) -> tuple[float, float]:
    """yt-dlp coupe sans réencoder, donc au keyframe le plus proche : on retrouve le vrai début par l'audio."""
    ref_start = max(0.0, requested - SYNC_SEARCH)
    reference = read_pcm(scout_audio, ref_start, SYNC_PROBE + 2 * SYNC_SEARCH, SYNC_SR)
    probe = read_pcm(clip, 0, SYNC_PROBE, SYNC_SR)
    lag, quality = find_offset(reference, probe)
    if quality < SYNC_MIN_QUALITY:
        return requested, quality
    return ref_start + lag / SYNC_SR, quality


def fetch_windows(
    slug: str,
    scout: dict[str, Any],
    steps: Steps,
    max_height: int = 1080,
    force: bool = False,
    top: int | None = None,
) -> list[FetchedWindow]:
    """Télécharge les plages des fenêtres du scout (toutes, ou seulement les `top` meilleures)."""
    url, vid = scout["url"], scout["video_id"]
    check_source(load_campaign(slug), slug, url)
    work = WORK_DIR / vid
    out_dir = work / "windows"
    scout_audio = find_output(work, "audio")
    if scout_audio is None:
        raise FileNotFoundError(f"audio du scout absent dans {work} : relancer `qclip scout`")
    duration = float(scout["duration"])
    windows = scout["windows"][:top] if top else scout["windows"]
    fetched: list[FetchedWindow] = []
    for w in windows:
        stem = f"w_{w['rank']:02d}"
        if force:
            for old in out_dir.glob(f"{stem}.*"):
                old.unlink()
        start, end = max(0.0, w["start"] - MARGIN), min(duration, w["end"] + MARGIN)
        with steps.step(f"plage {w['rank']:02d}/{len(windows)}"):
            path = download_section(url, start, end, out_dir, stem, max_height)
            exact, quality = real_start(scout_audio, path, start)
            info = ffprobe(path)
        fetched.append(
            FetchedWindow(w["rank"], path.name, start, end, round(exact, 3), info.duration, round(quality, 3))
        )
        steps.info(
            f"{stem} : {info.width}x{info.height} {info.fps:g} fps, {info.duration:.1f} s, "
            f"{path.stat().st_size / 1e6:.0f} Mo, début réel {exact - start:+.2f} s (accord {quality:.2f})"
        )

    (out_dir / "windows.json").write_text(
        json.dumps([asdict(f) for f in fetched], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    record_source(slug, url, vid, [(f.start, f.start + f.duration) for f in fetched])
    return fetched
