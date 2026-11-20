"""Parakeet TDT 0.6B v3 via onnx-asr, sur CPU, découpé par Silero VAD (fenêtre max ~20-30 s par appel)."""

import os
from pathlib import Path

from qclip.asr.base import Word, fix_overlaps, words_from_tokens

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")  # Windows sans mode développeur : cache sans symlinks

MAX_SPEECH_S = 20


class ParakeetTranscriber:
    name = "parakeet"

    def __init__(self, model: str = "nemo-parakeet-tdt-0.6b-v3", quantization: str | None = "int8") -> None:
        import onnx_asr

        self.model = f"{model} ({quantization or 'fp32'})"
        vad = onnx_asr.load_vad("silero")
        asr = onnx_asr.load_model(model, quantization=quantization)
        self._asr = asr.with_vad(vad, max_speech_duration_s=MAX_SPEECH_S).with_timestamps()

    def transcribe(self, wav: Path) -> list[Word]:
        words: list[Word] = []
        for seg in self._asr.recognize(str(wav)):
            if seg.tokens and seg.timestamps:
                words += words_from_tokens(seg.tokens, seg.timestamps, seg.logprobs, seg.start, seg.end)
        return fix_overlaps(words)
