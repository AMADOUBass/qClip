"""Backends de transcription derrière l'interface `Transcriber` (import paresseux : chaque backend tire ses libs)."""

from qclip.asr.base import Transcriber, Word

BACKENDS = ("parakeet", "whisper", "qwen3")
DEFAULT_MODELS = {"parakeet": "nemo-parakeet-tdt-0.6b-v3", "whisper": "small", "qwen3": "Qwen/Qwen3-ASR-0.6B"}


def get_transcriber(
    backend: str,
    model: str | None = None,
    quantization: str | None = "int8",
    language: str = "fr",
    threads: int = 4,
    prompt: str = "",
) -> Transcriber:
    """Charge le modèle du backend demandé (peut prendre de 10 s à 1 min et télécharger le modèle la 1re fois)."""
    model = model or DEFAULT_MODELS.get(backend, "")
    if backend == "parakeet":
        from qclip.asr.parakeet import ParakeetTranscriber

        return ParakeetTranscriber(model, quantization)
    if backend == "whisper":
        from qclip.asr.whisper import WhisperTranscriber

        return WhisperTranscriber(model, threads=threads, language=language, prompt=prompt)
    if backend == "qwen3":
        from qclip.asr.qwen3 import Qwen3Transcriber

        return Qwen3Transcriber(model, language=language, threads=threads)
    raise ValueError(f"backend inconnu {backend!r} : {', '.join(BACKENDS)}")


__all__ = ["BACKENDS", "DEFAULT_MODELS", "Transcriber", "Word", "get_transcriber"]
