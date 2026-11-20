"""Séparation voix / reste avec audio-separator, uniquement sur des fenêtres courtes (jamais une VOD entière)."""

import gc
import logging
from pathlib import Path

from qclip import ROOT

MODELS_DIR = ROOT / "models" / "audio-separator"


class VocalSeparator:
    """Charge un modèle une fois, puis sépare plusieurs fichiers. Libérer avec `close()` avant de charger l'ASR."""

    def __init__(self, model: str) -> None:
        from audio_separator.separator import Separator

        self.model = model
        self._separator = Separator(
            log_level=logging.WARNING,
            model_file_dir=str(MODELS_DIR),
            output_format="WAV",
            sample_rate=44100,
        )
        self._separator.load_model(model_filename=model)

    def separate(self, audio: Path, out_dir: Path) -> tuple[Path, Path]:
        """Renvoie (voix, reste) au format WAV 44,1 kHz dans out_dir."""
        out_dir.mkdir(parents=True, exist_ok=True)
        self._separator.output_dir = str(out_dir)
        if self._separator.model_instance is not None:  # le modèle garde son propre output_dir
            self._separator.model_instance.output_dir = str(out_dir)
        outputs = [out_dir / Path(p).name for p in self._separator.separate(str(audio))]
        vocals = [p for p in outputs if "(vocals)" in p.name.lower()]
        others = [p for p in outputs if "(vocals)" not in p.name.lower()]
        if len(vocals) != 1 or not others:
            raise RuntimeError(f"sorties inattendues de {self.model} : {[p.name for p in outputs]}")
        return vocals[0], others[0]

    def close(self) -> None:
        del self._separator
        gc.collect()
