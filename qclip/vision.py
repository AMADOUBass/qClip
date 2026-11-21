"""Images du début d'un clip vérifiées par un LLM vision local (SPEC §4.9, optionnel : `llm.use_vision`).

8 petites images (7 dans les 7 premières secondes + la miniature) envoyées en une seule requête à Ollama, réponse
JSON imposée par un schéma. Le modèle est déchargé ensuite (keep_alive=0) : un seul modèle en mémoire à la fois.
"""

import contextlib
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

FRAME_TIMES = [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5]  # secondes depuis le début du clip
FRAME_WIDTH = 384  # petites images : moins de jetons, moins de RAM
MIN_CONFIDENCE = 0.6
OLLAMA_HOST = "http://127.0.0.1:11434"

PROMPT = """These {n} images are frames from the first 7 seconds of a short vertical clip cut from a live stream
(frames 1-7, in order), plus its thumbnail (frame {n}). YouTube limits ads when the first seconds show graphic
violence or gore.

Answer in JSON:
- graphic_violence: true only for realistic, graphic violence (people being hurt, real fights with injuries, shootings
  of people, bloody scenes). Video game action without blood, people talking, gestures, jokes, a raised voice are NOT
  graphic violence.
- gore: true if blood, wounds or body parts are clearly visible.
- violent_frames: numbers (1-{n}) of the frames that show it, empty list if none.
- confidence: your confidence between 0 and 1.
- description: what the frames show, in French, 20 words max."""


class VisionVerdict(BaseModel):
    graphic_violence: bool
    gore: bool
    violent_frames: list[int] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    description: str = Field(max_length=300)


def frame(clip: Path, t: float, out: Path) -> Path:
    """Une image du clip à l'instant t, réduite à FRAME_WIDTH de large (JPEG)."""
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(clip), "-frames:v", "1",
         "-vf", f"scale={FRAME_WIDTH}:-2", "-q:v", "4", str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=False,
    )  # fmt: skip
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(f"image à {t:.1f} s impossible : {result.stderr.strip()[-200:]}")
    return out


def check_images(clip: Path, thumbnail: Path | None, model: str, keep_loaded: bool = False) -> dict[str, Any]:
    """Verdict du LLM vision sur le début du clip. Lève RuntimeError si Ollama ou le modèle manquent."""
    from ollama import Client, ResponseError

    client = Client(host=OLLAMA_HOST)
    try:
        installed = {m.model for m in client.list().models if m.model}
    except Exception as e:  # serveur arrêté, port fermé…
        raise RuntimeError(f"Ollama injoignable sur {OLLAMA_HOST} : lancer l'application Ollama ({e})") from e
    if model not in installed and f"{model}:latest" not in installed:
        raise RuntimeError(
            f"modèle {model!r} absent d'Ollama : `ollama pull {model}` (installés : {sorted(installed)})"
        )
    with tempfile.TemporaryDirectory(prefix="qclip-vision-") as tmp:
        images = [frame(clip, t, Path(tmp) / f"f{i}.jpg") for i, t in enumerate(FRAME_TIMES, 1)]
        if thumbnail and thumbnail.exists():
            images.append(frame(thumbnail, 0, Path(tmp) / "thumb.jpg"))
        start = time.perf_counter()
        try:
            response = client.chat(
                model=model,
                messages=[{"role": "user", "content": PROMPT.format(n=len(images)), "images": images}],
                format=VisionVerdict.model_json_schema(),
                options={"temperature": 0, "num_ctx": 4096},
                think=False,
                keep_alive="5m" if keep_loaded else 0,
            )
        except ResponseError as e:
            raise RuntimeError(f"erreur Ollama : {e}") from e
        finally:
            if not keep_loaded:
                with contextlib.suppress(Exception):
                    client.chat(model=model, messages=[], keep_alive=0)  # décharge le modèle : rend la RAM
    verdict = VisionVerdict.model_validate_json(response.message.content or "")
    flagged = (verdict.graphic_violence or verdict.gore) and verdict.confidence >= MIN_CONFIDENCE
    times = [*FRAME_TIMES, None]
    return {
        **verdict.model_dump(),
        "flagged": flagged,
        "at": [times[i - 1] for i in verdict.violent_frames if 1 <= i <= len(times) and times[i - 1] is not None],
        "model": model,
        "seconds": round(time.perf_counter() - start, 1),
    }
