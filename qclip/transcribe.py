"""Transcription par fenêtre (SPEC §4.4) → work/<id>/windows/w_<n>.transcript.json, temps ramenés à la VOD."""

import gc
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from qclip.asr import get_transcriber
from qclip.ingest import load_fetched, stem_paths
from qclip.sources import WORK_DIR
from qclip.steps import Steps
from qclip.utils.ffmpeg import media_duration


def transcript_path(windows_dir: Path, rank: int) -> Path:
    return windows_dir / f"w_{rank:02d}.transcript.json"


def transcribe_windows(
    vid: str,
    steps: Steps,
    backend: str = "parakeet",
    model: str | None = None,
    quantization: str | None = "int8",
    language: str = "fr",
    threads: int = 4,
    prompt: str = "",
    top: int | None = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    windows_dir = WORK_DIR / vid / "windows"
    todo = []
    for w in load_fetched(vid, top):
        vocals, _ = stem_paths(windows_dir, w["rank"])
        if not vocals.exists():
            raise FileNotFoundError(f"{vocals.name} absent : lancer d'abord `qclip ingest`")
        if force or not transcript_path(windows_dir, w["rank"]).exists():
            todo.append((w, vocals))
    if not todo:
        steps.info("toutes les plages sont déjà transcrites (--force pour refaire)")
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(windows_dir.glob("w_*.transcript.json"))]

    with steps.step(f"chargement de {backend}"):
        transcriber = get_transcriber(backend, model, quantization, language, threads, prompt)
    results = []
    try:
        for i, (w, vocals) in enumerate(todo, 1):
            with steps.step(f"plage {i}/{len(todo)} (n°{w['rank']:02d}, {w['duration']:.0f} s)"):
                words = transcriber.transcribe(vocals)
            offset = float(w["start"])
            data = {
                "rank": w["rank"],
                "backend": transcriber.name,
                "model": transcriber.model,
                "window_start": offset,
                "duration": media_duration(vocals),
                "text": " ".join(word.text for word in words),
                # Temps dans la VOD ; temps dans le fichier de la plage = start - window_start.
                "words": [
                    {**asdict(word), "start": round(word.start + offset, 3), "end": round(word.end + offset, 3)}
                    for word in words
                ],
            }
            transcript_path(windows_dir, w["rank"]).write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            steps.info(f"w_{w['rank']:02d} : {len(words)} mots — {data['text'][:110]}…")
            results.append(data)
    finally:
        del transcriber
        gc.collect()
    return results
