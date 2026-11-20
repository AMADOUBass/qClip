"""Signaux fins sur chaque plage + choix d'un passage par plage → work/<id>/candidates.json (SPEC §4.5)."""

import json
from pathlib import Path
from typing import Any

import numpy as np

from qclip.campaign import load_campaign
from qclip.config import Config, cpu_threads, load_config
from qclip.ingest import load_fetched, stem_paths
from qclip.score import choose_segment, dedupe, pooled_z, smooth
from qclip.signals import STEP, ClapScorer, grid, scene_cuts, speech_features, voice_loudness
from qclip.sources import WORK_DIR
from qclip.steps import Steps
from qclip.transcribe import transcript_path

EVENT_NAMES = {
    "people laughing": "rires",
    "person screaming": "cris",
    "explosion": "explosion",
    "gunshots": "coups de feu",
    "police siren": "sirène",
    "car crash": "accident",
}
SCORE_SMOOTH = int(3 / STEP)  # lissage du score combiné sur 3 s


def window_signals(
    w: dict[str, Any], windows_dir: Path, config: Config, use_scenes: bool, force: bool
) -> dict[str, np.ndarray]:
    """Signaux bon marché d'une plage (volume, parole, coupes), en cache dans w_<n>.signals.npz."""
    cache = windows_dir / f"w_{w['rank']:02d}.signals.npz"
    if cache.exists() and not force:
        with np.load(cache) as data:
            return {k: data[k] for k in data.files}
    times = grid(w["start"], w["duration"])
    vocals, _ = stem_paths(windows_dir, w["rank"])
    words = json.loads(transcript_path(windows_dir, w["rank"]).read_text(encoding="utf-8"))["words"]
    signals = {"times": times, "loudness": voice_loudness(vocals, w["start"], times)}
    signals |= speech_features(words, times, config.keywords)
    signals["cuts"] = np.array(scene_cuts(windows_dir / w["file"], w["start"]) if use_scenes else [])
    np.savez_compressed(
        cache,
        times=signals["times"],
        loudness=signals["loudness"],
        word_rate=signals["word_rate"],
        keywords=signals["keywords"],
        shouts=signals["shouts"],
        cuts=signals["cuts"],
    )
    return signals


def clap_signals(
    todo: list[dict[str, Any]], windows_dir: Path, config: Config, steps: Steps, force: bool
) -> dict[int, np.ndarray]:
    """Probabilités CLAP par plage (en cache dans w_<n>.clap.npy). Le modèle est chargé une seule fois."""
    out: dict[int, np.ndarray] = {}
    missing = []
    for w in todo:
        cache = windows_dir / f"w_{w['rank']:02d}.clap.npy"
        if cache.exists() and not force:
            out[w["rank"]] = np.load(cache)
        else:
            missing.append(w)
    if not missing:
        return out
    with steps.step("chargement de CLAP"):
        clap = ClapScorer(config.audio_event_labels, threads=cpu_threads(config))
    try:
        for w in missing:
            _, other = stem_paths(windows_dir, w["rank"])
            with steps.step(f"CLAP plage {w['rank']:02d}"):
                matrix = clap.score(other, w["start"], grid(w["start"], w["duration"]))
            np.save(windows_dir / f"w_{w['rank']:02d}.clap.npy", matrix)
            out[w["rank"]] = matrix
    finally:
        clap.close()
    return out


def chat_ratio(chat: np.ndarray, peak: float, span: float = 5.0) -> float:
    """Activité du chat autour du pic, rapportée à la moyenne de la VOD."""
    if len(chat) == 0 or chat.mean() <= 0:
        return 0.0
    a, b = max(0, int(peak - span)), min(len(chat), int(peak + span) + 1)
    return float(chat[a:b].mean() / chat.mean())


def explain(
    i: int, times: np.ndarray, parts: dict[str, np.ndarray], events: np.ndarray, labels: list[str], chat_x: float
) -> list[str]:
    """Raisons lisibles du score, à partir des signaux autour du pic (± 3 s)."""
    a, b = max(0, i - int(3 / STEP)), min(len(times), i + int(3 / STEP) + 1)
    reasons = []
    if chat_x >= 1.5:
        reasons.append(f"chat ×{chat_x:.1f}")
    if len(events):
        for j, label in enumerate(labels):
            p = float(events[a:b, j].max())
            z = float(parts["events_z"][a:b].max())
            if p >= 0.5 and z >= 0.5:
                reasons.append(f"{EVENT_NAMES.get(label, label)} ({p:.2f})")
    if parts["loud_z"][a:b].max() >= 1.5:
        reasons.append("voix forte")
    if parts["keywords"][a:b].sum() > 0:
        reasons.append("mots-clés")
    if parts["shouts"][a:b].sum() > 0:
        reasons.append("exclamations")
    if parts["rate_z"][a:b].max() >= 1.5:
        reasons.append("débit rapide")
    return reasons


def build_candidates(
    slug: str, vid: str, steps: Steps, use_clap: bool | None = None, use_scenes: bool | None = None, force: bool = False
) -> list[dict[str, Any]]:
    config, brief = load_config(), load_campaign(slug)
    use_clap = config.features.clap if use_clap is None else use_clap
    use_scenes = config.features.scenes if use_scenes is None else use_scenes
    work = WORK_DIR / vid
    windows_dir = work / "windows"
    windows = load_fetched(vid)
    with np.load(work / "scout_signals.npz") as data:
        scout_chat_z, scout_chat = data["z_chat"], data["chat"]

    per_window = []
    for w in windows:
        if not transcript_path(windows_dir, w["rank"]).exists():
            raise FileNotFoundError(f"transcription de la plage {w['rank']} absente : lancer `qclip transcribe`")
        with steps.step(f"signaux plage {w['rank']:02d}"):
            per_window.append(window_signals(w, windows_dir, config, use_scenes, force))
    events = clap_signals(windows, windows_dir, config, steps, force) if use_clap else {}

    with steps.step("score + choix des passages"):
        # Normalisation commune à toutes les plages : on compare chaque plage au niveau habituel de la VOD.
        loud_z = pooled_z([smooth(s["loudness"], int(1 / STEP)) for s in per_window])
        speech = [s["word_rate"] + 2 * s["keywords"] + s["shouts"] for s in per_window]
        speech_z = pooled_z(speech)
        rate_z = pooled_z([s["word_rate"] for s in per_window])
        ev = [events[w["rank"]].max(axis=1) if w["rank"] in events else np.zeros(len(s["times"])) for w, s in
              zip(windows, per_window, strict=True)]  # fmt: skip
        events_z = pooled_z(ev)

        candidates = []
        for k, (w, s) in enumerate(zip(windows, per_window, strict=True)):
            times = s["times"]
            chat_z = np.interp(times, np.arange(len(scout_chat_z)), scout_chat_z) if len(scout_chat_z) else 0 * times
            weights = config.weights
            combined = (
                weights.chat * chat_z
                + weights.loudness * loud_z[k]
                + weights.audio_events * events_z[k]
                + weights.speech_energy * speech_z[k]
            )
            score = smooth(combined, SCORE_SMOOTH)
            words = json.loads(transcript_path(windows_dir, w["rank"]).read_text(encoding="utf-8"))["words"]
            seg = choose_segment(
                times, score, words, [float(c) for c in s["cuts"]], brief.clip.min_len, brief.clip.max_len,
                config.clips.preroll, (w["start"], w["start"] + w["duration"]),
            )  # fmt: skip
            i_peak = int(np.argmin(np.abs(times - seg.peak)))
            parts = {"loud_z": loud_z[k], "events_z": events_z[k], "rate_z": rate_z[k],
                     "keywords": s["keywords"], "shouts": s["shouts"]}  # fmt: skip
            reasons = explain(
                i_peak, times, parts, events.get(w["rank"], np.zeros((0, 0))), config.audio_event_labels,
                chat_ratio(scout_chat, seg.peak),
            )  # fmt: skip
            inside = [x for x in words if seg.start <= x["start"] and x["end"] <= seg.end]
            a, b = max(0, i_peak - int(2 / STEP)), i_peak + int(2 / STEP) + 1
            candidates.append(
                {
                    "video_id": vid,
                    "window": w["rank"],
                    "file": f"windows/{w['file']}",
                    "start": seg.start,
                    "end": seg.end,
                    "duration": round(seg.duration, 2),
                    "file_start": round(seg.start - w["start"], 3),  # début dans le fichier de la plage
                    "peak": seg.peak,
                    "score": round(float(score[a:b].mean()), 3),
                    "reasons": reasons,
                    "text": " ".join(x["text"] for x in inside),
                }
            )
        kept = dedupe(candidates)
        for n, c in enumerate(kept, 1):
            c["id"] = n
    out = {
        "campaign": slug,
        "video_id": vid,
        "clap": use_clap,
        "scenes": use_scenes,
        "weights": config.weights.model_dump(),
        "candidates": kept,
    }
    (work / "candidates.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return kept
