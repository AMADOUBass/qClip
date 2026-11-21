"""`bench-asr`, `bench-sep` et `bench-vision` : comparer les backends sur un même extrait (SPEC §5, jalon M2)."""

import gc
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from qclip.asr import get_transcriber
from qclip.asr.base import Word, word_error_rate
from qclip.ingest import to_wav
from qclip.separation import VocalSeparator
from qclip.steps import Steps
from qclip.utils.ffmpeg import media_duration

SEP_MODELS = ("Kim_Vocal_2.onnx", "UVR-MDX-NET-Voc_FT.onnx", "vocals_mel_band_roformer.ckpt")


@dataclass
class AsrResult:
    name: str  # backend (bench-asr) ou modèle de séparation (bench-sep)
    model: str
    load_s: float
    run_s: float
    audio_s: float
    words: int
    confidence: float | None  # moyenne des confiances par mot
    wer_vs_first: float | None  # écart avec le premier résultat (référence = parakeet / sans séparation)
    text: str

    @property
    def rtf(self) -> float:
        return self.run_s / self.audio_s if self.audio_s else 0.0


def mean_confidence(words: list[Word]) -> float | None:
    values = [w.confidence for w in words if w.confidence is not None]
    return round(sum(values) / len(values), 3) if values else None


def as_16k(audio: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    return to_wav(audio, out_dir / f"{audio.stem}.16k.wav", 16000)


def bench_asr(audio: Path, backends: list[str], steps: Steps, threads: int = 4, prompt: str = "") -> list[AsrResult]:
    out_dir = audio.parent / "bench"
    wav = as_16k(audio, out_dir)
    duration = media_duration(wav)
    results: list[AsrResult] = []
    for backend in backends:
        start = time.perf_counter()
        with steps.step(f"{backend} : chargement"):
            transcriber = get_transcriber(backend, threads=threads, prompt=prompt)
        load_s = time.perf_counter() - start
        start = time.perf_counter()
        with steps.step(f"{backend} : transcription de {duration:.0f} s"):
            words = transcriber.transcribe(wav)
        run_s = time.perf_counter() - start
        text = " ".join(w.text for w in words)
        wer = word_error_rate(results[0].text, text) if results else None
        results.append(
            AsrResult(
                backend, transcriber.model, load_s, run_s, duration, len(words), mean_confidence(words), wer, text
            )
        )
        del transcriber  # un seul modèle en mémoire à la fois
        gc.collect()
    save(out_dir / f"{audio.stem}.bench-asr.json", results)
    return results


def bench_sep(audio: Path, models: list[str], steps: Steps, threads: int = 4) -> list[AsrResult]:
    """Chaque modèle sépare l'extrait, puis Parakeet transcrit chaque piste « voix » (+ l'audio brut en référence)."""
    out_dir = audio.parent / "bench" / f"{audio.stem}.sep"
    out_dir.mkdir(parents=True, exist_ok=True)
    full = to_wav(audio, out_dir / "full.wav", 44100, mono=False)
    duration = media_duration(full)
    variants: list[tuple[str, Path, float, float]] = [("aucune (audio brut)", as_16k(audio, out_dir), 0.0, 0.0)]
    for model in models:
        start = time.perf_counter()
        with steps.step(f"{model} : chargement"):
            separator = VocalSeparator(model)
        load_s = time.perf_counter() - start
        start = time.perf_counter()
        with steps.step(f"{model} : séparation de {duration:.0f} s"):
            vocals, other = separator.separate(full, out_dir / "raw")
        run_s = time.perf_counter() - start
        separator.close()
        variants.append((model, to_wav(vocals, out_dir / f"{Path(model).stem}.vocals.wav", 16000), load_s, run_s))
        other.unlink(missing_ok=True)
        vocals.unlink(missing_ok=True)

    with steps.step("parakeet : chargement"):
        transcriber = get_transcriber("parakeet", threads=threads)
    results: list[AsrResult] = []
    for name, wav, load_s, run_s in variants:
        with steps.step(f"parakeet sur « {name} »"):
            words = transcriber.transcribe(wav)
        text = " ".join(w.text for w in words)
        wer = word_error_rate(results[0].text, text) if results else None
        results.append(
            AsrResult(name, wav.name, load_s, run_s, duration, len(words), mean_confidence(words), wer, text)
        )
    del transcriber
    gc.collect()
    full.unlink(missing_ok=True)
    save(out_dir / "bench-sep.json", results)
    return results


def save(path: Path, results: list[AsrResult]) -> None:
    data = [{**asdict(r), "rtf": round(r.rtf, 3)} for r in results]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class VisionResult:
    model: str
    graphic_violence: bool
    gore: bool
    violent_frames: list[int]
    flagged: bool
    confidence: float
    description: str
    seconds: float


def bench_vision(clip: Path, models: list[str], thumbnail: Path | None = None) -> list[VisionResult]:
    """Chaque modèle vision analyse les 7 premières secondes du clip et retourne son verdict de démonétisation."""
    from qclip.vision import check_images

    results: list[VisionResult] = []
    for model in models:
        verdict = check_images(clip, thumbnail, model)
        results.append(
            VisionResult(
                model=verdict["model"],
                graphic_violence=verdict["graphic_violence"],
                gore=verdict["gore"],
                violent_frames=verdict["violent_frames"],
                flagged=verdict["flagged"],
                confidence=verdict["confidence"],
                description=verdict["description"],
                seconds=verdict["seconds"],
            )
        )
    out = clip.parent / "bench" / f"{clip.stem}.bench-vision.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2), encoding="utf-8")
    return results
