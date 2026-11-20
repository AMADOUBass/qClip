"""Qwen3-ASR-0.6B + Qwen3-ForcedAligner-0.6B (extra optionnel : `uv sync --extra qwen`).

Sur cette machine, un seul modèle en mémoire à la fois : à chaque fichier, on charge l'ASR, on le libère,
puis on charge l'aligneur. Lent, mais réservé au bench. float32 : le i7-8550U n'accélère pas le bfloat16.
"""

import gc
import os
from pathlib import Path

from qclip.asr.base import Word, fix_overlaps, merge_punctuation

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

LANGUAGES = {"fr": "French", "en": "English"}


class Qwen3Transcriber:
    name = "qwen3"

    def __init__(
        self,
        model: str = "Qwen/Qwen3-ASR-0.6B",
        aligner: str = "Qwen/Qwen3-ForcedAligner-0.6B",
        language: str = "fr",
        threads: int = 4,
    ) -> None:
        try:
            import qwen_asr  # noqa: F401  # ty: ignore[import-not-found]  (extra optionnel)
            import torch
        except ImportError as e:
            raise RuntimeError("backend qwen3 non installé : lancer `uv sync --extra qwen`") from e
        torch.set_num_threads(threads)
        self.model = model.split("/")[-1]
        self._asr_name, self._aligner_name = model, aligner
        self.language = LANGUAGES.get(language, language)

    def transcribe(self, wav: Path) -> list[Word]:
        import torch
        from qwen_asr import Qwen3ASRModel, Qwen3ForcedAligner  # ty: ignore[import-not-found]

        asr = Qwen3ASRModel.from_pretrained(self._asr_name, dtype=torch.float32, device_map="cpu", max_new_tokens=1024)
        text = asr.transcribe(audio=str(wav), language=self.language)[0].text
        del asr
        gc.collect()
        if not text.strip():
            return []
        aligner = Qwen3ForcedAligner.from_pretrained(self._aligner_name, dtype=torch.float32, device_map="cpu")
        items = aligner.align(audio=str(wav), text=text, language=self.language)[0]
        del aligner
        gc.collect()
        # L'aligneur ne donne pas de confiance par mot.
        words = [Word(i.text, round(i.start_time, 3), round(i.end_time, 3), None) for i in items if i.text.strip()]
        return fix_overlaps(merge_punctuation(attach_punctuation(words, text)))


def attach_punctuation(words: list[Word], text: str) -> list[Word]:
    """L'aligneur renvoie les mots sans ponctuation : on reprend, dans le texte de l'ASR et dans l'ordre,
    la graphie exacte du mot et la ponctuation qui le suit (« Écoute-moi, » → « Écoute », « moi, »)."""
    lower = text.lower()
    out: list[Word] = []
    pos = 0
    for w in words:
        i = lower.find(w.text.lower(), pos)
        if i < 0:
            out.append(w)
            continue
        j = i + len(w.text)
        while j < len(text) and not text[j].isspace() and not text[j].isalnum() and text[j] not in "-'’":
            j += 1
        out.append(Word(text[i:j], w.start, w.end, w.confidence))
        pos = j
    return out
