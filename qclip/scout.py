"""Repérage léger sur la VOD entière (SPEC §4.1) : chat + volume → meilleures fenêtres de ~75 s.

Seuls le chat (JSON) et l'audio basse qualité sont téléchargés ; aucun modèle ML ici.
"""

import json
import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from qclip.campaign import check_source, load_campaign
from qclip.chat import ChatMessage, download_chat, is_noise, is_reaction, load_chat
from qclip.config import Config, load_config
from qclip.sources import WORK_DIR, download_audio, load_info, twitch_vod_id, video_id
from qclip.steps import Steps
from qclip.utils.audio import loudness_per_second

MAX_OVERLAP = 0.3  # deux fenêtres ne se recouvrent jamais à plus de 30 %
PEAK_POSITION = 0.6  # le pic est placé à 60 % de la fenêtre : plus de contexte avant, la réaction après
ZSCORE_WINDOW = 600  # z-score glissant sur 10 min : une VOD change d'ambiance au fil des heures
MANUAL_HOSTS = ("drive.google.com", "dropbox.com")


@dataclass
class Window:
    rank: int
    start: float
    end: float
    peak: float
    score: float
    chat_z: float
    loudness_z: float


# --- signaux (fonctions pures, testées dans tests/test_scout.py) ---------------------------------


def moving_average(x: np.ndarray, width: int) -> np.ndarray:
    if width <= 1 or len(x) == 0:
        return x.astype(np.float64)
    return np.convolve(x, np.ones(width) / width, mode="same")


def rolling_zscore(x: np.ndarray, window: int = ZSCORE_WINDOW) -> np.ndarray:
    """(x - moyenne locale) / écart-type local, fenêtre centrée. 0 là où le signal est plat."""
    n = len(x)
    if n == 0:
        return np.zeros(0)
    x = x.astype(np.float64)
    c1 = np.concatenate([[0.0], np.cumsum(x)])
    c2 = np.concatenate([[0.0], np.cumsum(x**2)])
    idx = np.arange(n)
    lo = np.clip(idx - window // 2, 0, n)
    hi = np.clip(idx + window // 2 + 1, 0, n)
    count = hi - lo
    mean = (c1[hi] - c1[lo]) / count
    std = np.sqrt(np.maximum((c2[hi] - c2[lo]) / count - mean**2, 0))
    return np.where(std > 1e-6, (x - mean) / np.maximum(std, 1e-6), 0.0)


def chat_series(
    messages: list[ChatMessage], length: int, emotes: list[str], emote_bonus: float, delay: float
) -> np.ndarray:
    """Activité du chat par seconde, recalée de `delay` s en arrière (on réagit après le moment)."""
    series = np.zeros(length)
    for msg in messages:
        t = int(msg.offset - delay)
        if 0 <= t < length:
            series[t] += 1 + (emote_bonus if is_reaction(msg.text, emotes) else 0)
    return series


def combined_score(
    chat: np.ndarray | None, loudness_db: np.ndarray, config: Config
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Somme pondérée des z-scores. Renvoie (score, z_chat, z_loudness)."""
    z_loud = rolling_zscore(moving_average(loudness_db, 3))
    z_chat = rolling_zscore(moving_average(chat, 5)) if chat is not None else np.zeros_like(z_loud)
    score = config.weights.loudness * z_loud + (config.weights.chat * z_chat if chat is not None else 0)
    return moving_average(score, 5), z_chat, z_loud


def pick_windows(score: np.ndarray, window_len: float, count: int, max_overlap: float = MAX_OVERLAP) -> list[Window]:
    """Glouton : le meilleur pic d'abord, puis les suivants qui ne recouvrent pas trop les fenêtres déjà prises."""
    duration = len(score)
    length = min(window_len, duration)
    chosen: list[Window] = []
    for peak in np.argsort(score, kind="stable")[::-1]:
        start = float(np.clip(peak - PEAK_POSITION * length, 0, duration - length))
        end = start + length
        if all(min(end, w.end) - max(start, w.start) <= max_overlap * length for w in chosen):
            chosen.append(Window(len(chosen) + 1, start, end, float(peak), float(score[peak]), 0.0, 0.0))
            if len(chosen) == count:
                break
    return chosen


# --- orchestration -------------------------------------------------------------------------------


def scout_urls(slug: str, url: str | None) -> list[str]:
    brief = load_campaign(slug)
    if url:
        check_source(brief, slug, url)
        return [url]
    return [u for u in brief.sources if not any(host in u for host in MANUAL_HOSTS)]


def scout_source(slug: str, url: str, steps: Steps, force: bool = False) -> dict[str, Any]:
    """Repère les fenêtres d'une source et écrit work/<id>/scout.json. Réutilise chat, audio et volume déjà calculés."""
    config = load_config()
    check_source(load_campaign(slug), slug, url)
    vid = video_id(url)
    work = WORK_DIR / vid
    if force:
        for name in ["info.json", "chat.json", "loudness.npy", "scout.json", "scout_signals.npz"]:
            (work / name).unlink(missing_ok=True)
        for audio in work.glob("audio.*"):
            audio.unlink()

    with steps.step("métadonnées"):
        info = load_info(url, work)
    steps.info(f"{vid} : « {info.get('title')} » — {format_hms(info.get('duration') or 0)}")

    messages: list[ChatMessage] | None = None
    vod = twitch_vod_id(url)
    if vod:
        with steps.step("chat (TwitchDownloaderCLI)"):
            raw = load_chat(download_chat(vod, work / "chat.json"))
        messages = [m for m in raw if not is_noise(m, config.chat_bots)]
        reactions = sum(is_reaction(m.text, config.chat_emotes) for m in messages)
        steps.info(
            f"{len(raw)} messages de chat, {len(raw) - len(messages)} ignorés (bots, commandes), "
            f"{reactions} réactions (emotes / rires)"
        )
    else:
        steps.info("pas de replay de chat pour cette source : repérage au volume seul")

    with steps.step("audio basse qualité (yt-dlp)"):
        audio = download_audio(url, work)
    steps.info(f"audio : {audio.name}, {audio.stat().st_size / 1e6:.0f} Mo")

    loud_path = work / "loudness.npy"
    with steps.step("volume RMS par seconde"):
        if loud_path.exists():
            loudness = np.load(loud_path)
        else:
            loudness = loudness_per_second(audio)
            np.save(loud_path, loudness)

    with steps.step("score + fenêtres"):
        length = len(loudness)
        chat = (
            chat_series(messages, length, config.chat_emotes, config.scout.emote_bonus, config.scout.chat_delay)
            if messages
            else None
        )
        score, z_chat, z_loud = combined_score(chat, loudness, config)
        count = config.scout.windows_factor * config.clips.top_n
        windows = pick_windows(score, config.scout.window_len, count)
        for w in windows:
            w.chat_z, w.loudness_z = float(z_chat[int(w.peak)]), float(z_loud[int(w.peak)])
        np.savez_compressed(
            work / "scout_signals.npz",
            chat=chat if chat is not None else np.zeros(0),
            loudness_db=loudness,
            z_chat=z_chat,
            z_loudness=z_loud,
            score=score,
        )

    result = {
        "campaign": slug,
        "url": url,
        "video_id": vid,
        "title": info.get("title"),
        "duration": float(info.get("duration") or length),
        "has_chat": chat is not None,
        "chat_messages": len(messages or []),
        "params": {**config.scout.model_dump(), "count": count, "weights": config.weights.model_dump()},
        "timings": {k: round(v, 2) for k, v in steps.timings.items()},
        "windows": [asdict(w) for w in windows],
    }
    (work / "scout.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def load_scout(vid: str) -> dict[str, Any]:
    path = WORK_DIR / vid / "scout.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} absent : lancer d'abord `qclip scout`")
    return json.loads(path.read_text(encoding="utf-8"))


def scouted_videos(slug: str) -> list[str]:
    """Identifiants des vidéos déjà repérées pour cette campagne."""
    found = []
    for path in sorted(WORK_DIR.glob("*/scout.json")):
        if json.loads(path.read_text(encoding="utf-8")).get("campaign") == slug:
            found.append(path.parent.name)
    return found


def format_hms(seconds: float) -> str:
    seconds = max(0, math.floor(seconds))
    return f"{seconds // 3600:d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
