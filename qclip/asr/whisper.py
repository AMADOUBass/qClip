"""faster-whisper (CTranslate2) en int8 sur CPU, avec son VAD Silero intégré."""

import os
from pathlib import Path

from qclip.asr.base import Word, fix_overlaps, merge_punctuation

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


class WhisperTranscriber:
    name = "whisper"

    def __init__(self, model: str = "small", threads: int = 4, language: str = "fr", prompt: str = "") -> None:
        from faster_whisper import WhisperModel

        self.model = f"{model} (int8)"
        self.language = language
        self.prompt = prompt or None
        self._model = WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=threads)

    def transcribe(self, wav: Path) -> list[Word]:
        import soundfile

        # On passe un tableau numpy (mono 16 kHz) : faster-whisper 1.2.1 décode les fichiers avec une API de
        # PyAV supprimée dans PyAV 19 (`metadata_errors`).
        audio, sample_rate = soundfile.read(str(wav), dtype="float32", always_2d=False)
        if sample_rate != 16000 or audio.ndim != 1:
            raise RuntimeError(f"{wav.name} : mono 16 kHz attendu (reçu {sample_rate} Hz, {audio.ndim} dim.)")
        segments, _ = self._model.transcribe(
            audio,
            language=self.language,
            word_timestamps=True,
            vad_filter=True,
            initial_prompt=self.prompt,
            beam_size=5,
            condition_on_previous_text=False,  # limite les boucles / hallucinations sur l'audio de stream
        )
        words: list[Word] = []
        for seg in segments:
            for w in seg.words or []:
                if not w.word.strip():
                    continue
                # Un morceau sans espace initiale (« 'ai », « -moi ») continue le mot précédent du segment.
                if words and not w.word.startswith(" ") and w.start - words[-1].end < 0.3:
                    prev = words[-1]
                    conf = min(prev.confidence or 1.0, w.probability)
                    words[-1] = Word(prev.text + w.word.strip(), prev.start, round(w.end, 3), round(conf, 3))
                else:
                    words.append(Word(w.word.strip(), round(w.start, 3), round(w.end, 3), round(w.probability, 3)))
        return fix_overlaps(merge_punctuation(words))
