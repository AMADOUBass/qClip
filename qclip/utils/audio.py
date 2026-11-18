"""Lecture d'audio via ffmpeg en PCM mono, par blocs : une VOD de 4 h ne doit jamais tenir entière en RAM."""

import subprocess
from pathlib import Path

import numpy as np

from qclip.utils.ffmpeg import last_line


def loudness_per_second(audio: Path, sr: int = 8000) -> np.ndarray:
    """Volume RMS en dBFS, une valeur par seconde, calculé en flux (60 s à la fois)."""
    cmd = ["ffmpeg", "-v", "error", "-i", str(audio), "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"]
    values: list[np.ndarray] = []
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        assert proc.stdout is not None and proc.stderr is not None
        while chunk := proc.stdout.read(sr * 2 * 60):
            samples = np.frombuffer(chunk[: len(chunk) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768
            seconds = len(samples) // sr
            if seconds:
                blocks = samples[: seconds * sr].reshape(seconds, sr)
                values.append(np.sqrt(np.mean(blocks**2, axis=1)))
            if len(samples) - seconds * sr > sr // 2:  # dernière seconde incomplète mais significative
                values.append(np.array([np.sqrt(np.mean(samples[seconds * sr :] ** 2))]))
        err = proc.stderr.read().decode("utf-8", "replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg n'a pas pu lire {audio.name} : {last_line(err)}")
    rms = np.concatenate(values) if values else np.zeros(0, dtype=np.float32)
    return (20 * np.log10(rms + 1e-6)).astype(np.float32)


def read_pcm(path: Path, start: float, duration: float, sr: int = 8000) -> np.ndarray:
    """Extrait [start, start + duration] en float32 mono."""
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(start, 0):.3f}", "-t", f"{duration:.3f}", "-i", str(path),
           "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"]  # fmt: skip
    result = subprocess.run(cmd, capture_output=True, check=False, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg n'a pas pu lire {path.name} : {last_line(result.stderr.decode('utf-8', 'replace'))}"
        )
    return np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768


def find_offset(reference: np.ndarray, probe: np.ndarray) -> tuple[int, float]:
    """Position de `probe` dans `reference` (corrélation croisée par FFT) et qualité de l'accord (0 à 1)."""
    if len(probe) == 0 or len(reference) < len(probe):
        return 0, 0.0
    nfft = 1 << (len(reference) + len(probe) - 1).bit_length()
    corr = np.fft.irfft(np.fft.rfft(reference, nfft) * np.conj(np.fft.rfft(probe, nfft)), nfft)
    corr = corr[: len(reference) - len(probe) + 1]
    lag = int(np.argmax(corr))
    segment = reference[lag : lag + len(probe)]
    quality = float(corr[lag] / (np.linalg.norm(segment) * np.linalg.norm(probe) + 1e-9))
    return lag, quality
