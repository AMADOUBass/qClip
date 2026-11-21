"""Signaux fins par plage (SPEC §4.5) : volume de la voix, événements audio (CLAP), débit de parole, mots-clés,
coupes de scène. Tout est échantillonné sur une grille de STEP secondes, en temps de la VOD."""

import gc
import math
import os
import re
from pathlib import Path
from typing import Any

import numpy as np

from qclip.chat import normalize
from qclip.utils.ffmpeg import last_line, run

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

STEP = 0.5  # pas de la grille des signaux fins (s)
CLAP_MODEL = "laion/clap-htsat-unfused"
CLAP_WINDOW = 4.0  # durée d'un extrait écouté par CLAP (s)
CLAP_HOP = 3.0  # RTF 0,17 avec un pas de 2 s sur ce CPU ; 3 s suffit pour des événements de quelques secondes
# Libellés « de fond » : sans eux, le softmax de CLAP désignerait toujours un événement, même au calme.
CLAP_BACKGROUND = ["people talking calmly", "background music", "silence", "video game background sounds"]
SCENE_THRESHOLD = 10.0  # score scdet de ffmpeg (0-100)


def grid(start: float, duration: float) -> np.ndarray:
    return start + np.arange(0, duration, STEP)


def voice_loudness(wav: Path, start: float, times: np.ndarray) -> np.ndarray:
    """Volume RMS (dBFS) par pas de STEP s."""
    import soundfile

    audio, sr = soundfile.read(str(wav), dtype="float32", always_2d=False)
    hop = int(sr * STEP)
    values = np.full(len(times), -90.0, dtype=np.float32)
    for i, t in enumerate(times):
        a = int((t - start) * sr)
        chunk = audio[a : a + hop]
        if len(chunk):
            values[i] = 20 * np.log10(np.sqrt(np.mean(chunk**2)) + 1e-6)
    return values


def speech_features(words: list[dict[str, Any]], times: np.ndarray, keywords: list[str]) -> dict[str, np.ndarray]:
    """Débit (mots/s, fenêtre glissante de 2 s), mots-clés FR et exclamations, par pas de STEP s."""
    rate = np.zeros(len(times))
    hits = np.zeros(len(times))
    shouts = np.zeros(len(times))
    targets = [normalize(k) for k in keywords]
    multi = [k.lower() for k in keywords if " " in k]
    for w in words:
        i = int((w["start"] - times[0]) / STEP)
        if not 0 <= i < len(times):
            continue
        lo, hi = max(0, i - int(1 / STEP)), min(len(times), i + int(1 / STEP) + 1)
        rate[lo:hi] += 1 / 2.0  # chaque mot compte pour 1/2 s sur une fenêtre de 2 s
        token = normalize(w["text"])
        if token in targets:
            hits[i] += 1
        if w["text"].rstrip().endswith(("!", "?!")) or (len(w["text"]) > 2 and w["text"].isupper()):
            shouts[i] += 1
    text = " ".join(w["text"].lower() for w in words)
    for phrase in multi:  # « c'est pas possible » : on marque le début de chaque occurrence
        for m in re.finditer(re.escape(phrase), text):
            k = text[: m.start()].count(" ")
            if k < len(words):
                i = int((words[k]["start"] - times[0]) / STEP)
                if 0 <= i < len(times):
                    hits[i] += 1
    return {"word_rate": rate, "keywords": hits, "shouts": shouts}


class ClapScorer:
    """CLAP zéro-shot : probabilité de chaque libellé d'événement, par extrait de CLAP_WINDOW s."""

    def __init__(self, labels: list[str], threads: int = 4) -> None:
        import torch
        from transformers import ClapModel, ClapProcessor

        torch.set_num_threads(threads)
        self.labels = labels
        self._all = labels + CLAP_BACKGROUND
        self._processor = ClapProcessor.from_pretrained(CLAP_MODEL)
        self._model = ClapModel.from_pretrained(CLAP_MODEL).eval()

    def score(self, wav: Path, start: float, times: np.ndarray, batch: int = 8) -> np.ndarray:
        """Matrice (len(times), len(labels)) : probabilité de chaque événement, interpolée sur la grille."""
        import soundfile
        import torch

        audio, sr = soundfile.read(str(wav), dtype="float32", always_2d=False)
        if sr != 48000:
            raise RuntimeError(f"{wav.name} : CLAP attend du 48 kHz (reçu {sr})")
        size, hop = int(CLAP_WINDOW * sr), int(CLAP_HOP * sr)
        offsets = list(range(0, max(1, len(audio) - size + 1), hop))
        centers, probs = [], []
        for b in range(0, len(offsets), batch):
            chunks = [audio[o : o + size] for o in offsets[b : b + batch]]
            inputs = self._processor(text=self._all, audio=chunks, sampling_rate=sr, return_tensors="pt", padding=True)
            with torch.no_grad():
                p = self._model(**inputs).logits_per_audio.softmax(dim=-1)[:, : len(self.labels)]
            probs.append(p.numpy())
            centers += [start + (o + size / 2) / sr for o in offsets[b : b + batch]]
        matrix = np.concatenate(probs) if probs else np.zeros((0, len(self.labels)))
        if len(centers) < 2:
            return (
                np.repeat(matrix[:1], len(times), axis=0) if len(matrix) else np.zeros((len(times), len(self.labels)))
            )
        return np.stack([np.interp(times, centers, matrix[:, j]) for j in range(len(self.labels))], axis=1)

    def close(self) -> None:
        del self._model, self._processor
        gc.collect()


AROUND_S = 1.5  # demi-largeur des extraits analysés autour d'une borne (> CUT_SNAP de score.py)


def scene_cuts(video: Path, start: float, around: list[float] | None = None) -> list[float]:
    """Coupes de scène (temps VOD) par le filtre scdet de ffmpeg, sur une image réduite à 10 i/s.

    `around` (temps VOD) : n'analyser que ± AROUND_S autour de ces instants. Les coupes ne servent qu'à caler une borne
    à moins d'une seconde (score.snap_to_cuts) : 2 extraits de 3 s au lieu de toute la plage (≈ 8 x plus rapide, M7).
    """
    # Début des extraits sur la grille de 0,1 s du fichier : mêmes images échantillonnées (fps=10) qu'une analyse
    # de toute la plage, donc mêmes instants de coupe.
    spans = [(None, None)] if around is None else [
        (max(0.0, math.floor((t - start - AROUND_S) * 10) / 10), 2 * AROUND_S) for t in around]  # fmt: skip
    found: set[float] = set()
    for offset, length in spans:
        seek = [] if offset is None else ["-ss", f"{offset:.3f}", "-t", f"{length:.3f}"]
        result = run(
            ["ffmpeg", "-hide_banner", "-v", "error", *seek, "-skip_loop_filter", "all", "-threads", "4", "-i", video,
             "-an", "-vf", f"fps=10,scale=320:-2,scdet=threshold={SCENE_THRESHOLD},metadata=print:file=-",
             "-f", "null", "-"],
            timeout=900,
        )  # fmt: skip
        if result.returncode != 0:
            raise RuntimeError(f"détection des coupes impossible sur {video.name} : {last_line(result.stderr)}")
        found |= {round(start + (offset or 0.0) + float(t), 2)
                  for t in re.findall(r"lavfi\.scd\.time=([\d.]+)", result.stdout + result.stderr)}  # fmt: skip
    return sorted(found)
