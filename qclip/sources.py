"""Sources d'une campagne : identifiant de vidéo, métadonnées, téléchargements via yt-dlp, registre sources.json."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import download_range_func

from qclip import ROOT

WORK_DIR = ROOT / "work"
INPUT_DIR = ROOT / "input"
TWITCH_VOD_RE = re.compile(r"twitch\.tv/(?:[^/]+/)?videos?/(\d+)")


def twitch_vod_id(url: str) -> str | None:
    match = TWITCH_VOD_RE.search(url)
    return match.group(1) if match else None


def safe_id(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")[:80]


def ydl_options(**extra: Any) -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "concurrent_fragment_downloads": 4,  # HLS (Twitch) : 4 fragments en parallèle
        **extra,
    }


def fetch_info(url: str) -> dict[str, Any]:
    """Métadonnées yt-dlp (sans téléchargement), sérialisables en JSON."""
    with YoutubeDL(ydl_options()) as ydl:
        info = ydl.extract_info(url, download=False)
        return ydl.sanitize_info(info)


def video_id(url: str, info: dict[str, Any] | None = None) -> str:
    """Identifiant stable utilisé pour work/<video_id>/ : « twitch-123456789 », « youtube-abc », …"""
    vod = twitch_vod_id(url)
    if vod:
        return f"twitch-{vod}"
    info = info or fetch_info(url)
    return safe_id(f"{info.get('extractor_key', 'web')}-{info['id']}".lower())


def load_info(url: str, work: Path, force: bool = False) -> dict[str, Any]:
    """Métadonnées mises en cache dans work/<id>/info.json."""
    path = work / "info.json"
    if path.exists() and not force:
        return json.loads(path.read_text(encoding="utf-8"))
    info = fetch_info(url)
    work.mkdir(parents=True, exist_ok=True)
    # On ne garde que l'utile : la liste complète des formats pèse lourd et périme vite.
    keep = ["id", "title", "uploader", "duration", "extractor_key", "webpage_url", "upload_date", "timestamp"]
    slim = {k: info.get(k) for k in keep}
    path.write_text(json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")
    return slim


def find_output(directory: Path, stem: str) -> Path | None:
    """Fichier produit par yt-dlp (l'extension dépend de la source).

    Seulement « <stem>.<ext> » : les fichiers dérivés (w_01.clap.npy, w_01.raw16k.wav…) ne sont pas la vidéo.
    """
    for path in sorted(directory.glob(f"{stem}.*")):
        if path.stem == stem and path.suffix not in {".part", ".ytdl", ".json"}:
            return path
    return None


def download_audio(url: str, work: Path) -> Path:
    """Audio seul, qualité la plus basse disponible (sert au repérage : seul le volume compte)."""
    existing = find_output(work, "audio")
    if existing:
        return existing
    opts = ydl_options(
        format="worstaudio[vcodec=none]/bestaudio/worst",
        outtmpl={"default": str(work / "audio.%(ext)s")},
    )
    with YoutubeDL(opts) as ydl:
        if ydl.download([url]) != 0:
            raise RuntimeError(f"yt-dlp n'a pas pu télécharger l'audio de {url}")
    path = find_output(work, "audio")
    if path is None:
        raise RuntimeError("yt-dlp n'a produit aucun fichier audio")
    return path


def download_section(url: str, start: float, end: float, out_dir: Path, stem: str, max_height: int = 1080) -> Path:
    """Télécharge seulement [start, end] (secondes) de la vidéo, sans réencodage (coupe au keyframe le plus proche)."""
    existing = find_output(out_dir, stem)
    if existing:
        return existing
    out_dir.mkdir(parents=True, exist_ok=True)
    opts = ydl_options(
        format=f"b[height<={max_height}]/bv*[height<={max_height}]+ba/b",
        outtmpl={"default": str(out_dir / f"{stem}.%(ext)s")},
        download_ranges=download_range_func(None, [(start, end)]),
        force_keyframes_at_cuts=False,
        merge_output_format="mp4",
    )
    with YoutubeDL(opts) as ydl:
        if ydl.download([url]) != 0:
            raise RuntimeError(f"yt-dlp n'a pas pu télécharger la plage {start:.0f}-{end:.0f} s")
    path = find_output(out_dir, stem)
    if path is None:
        raise RuntimeError(f"yt-dlp n'a produit aucun fichier pour la plage {start:.0f}-{end:.0f} s")
    return path


def record_source(slug: str, url: str, vid: str, ranges: list[tuple[float, float]]) -> Path:
    """Ajoute / met à jour l'entrée de cette URL dans input/<campagne>/sources.json."""
    path = INPUT_DIR / slug / "sources.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    entries = [e for e in entries if e.get("url") != url]
    entries.append(
        {
            "url": url,
            "video_id": vid,
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "ranges": [[round(s, 2), round(e, 2)] for s, e in ranges],
        }
    )
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
