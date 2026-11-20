"""Rerank par LLM local (SPEC §4.6, optionnel) : Ollama note les meilleurs candidats et propose accroche + titre.

Résultats dans work/<id>/rerank.json (clé = passage), lus par `qclip render`. Lent sur CPU : seulement le top 2×N,
textes courts. Le modèle est déchargé à la fin (keep_alive=0) pour rendre la RAM.
"""

import contextlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from qclip.campaign import load_campaign
from qclip.config import load_config
from qclip.sources import WORK_DIR
from qclip.steps import Steps

OLLAMA_HOST = "http://127.0.0.1:11434"


class Verdict(BaseModel):
    score: int = Field(ge=0, le=10, description="potentiel viral du clip pour des inconnus qui scrollent, 0 à 10")
    hook: str = Field(description="accroche à l'écran, 8 mots maximum, en français, sans mentir sur le contenu")
    title: str = Field(description="titre du post, 60 caractères maximum, en français, sans clickbait trompeur")
    reason: str = Field(description="une phrase : pourquoi ce score")
    standalone: bool = Field(description="le clip se comprend-il sans connaître le contexte du live ?")


PROMPT = """Tu es monteur de clips courts (TikTok, Shorts, Reels) pour le streamer {creator}.
Voici un extrait de {duration:.0f} s d'un live, transcrit automatiquement (la transcription peut contenir des erreurs :
ne cite pas un passage qui n'a pas de sens).
Signaux mesurés : {reasons}.

Transcription :
\"\"\"{text}\"\"\"

Note ce clip pour des inconnus qui scrollent, propose une accroche (8 mots max) et un titre (60 caractères max),
en français familier comme le streamer, sans inventer ce qui ne se passe pas dans l'extrait. Réponds en JSON."""


def key(c: dict[str, Any]) -> str:
    return f"{c['window']}:{c['start']:.3f}:{c['end']:.3f}"


def load_rerank(vid: str) -> dict[str, dict[str, Any]]:
    path = WORK_DIR / vid / "rerank.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def clean(verdict: Verdict) -> dict[str, Any]:
    hook = " ".join(verdict.hook.strip().strip('"«»').split()[:8])
    title = verdict.title.strip().strip('"')
    title = title if len(title) <= 60 else title[:59].rsplit(" ", 1)[0] + "…"
    return {**verdict.model_dump(), "hook": hook, "title": title}


def rerank_candidates(slug: str, vid: str, steps: Steps, top: int | None = None, force: bool = False) -> Path:
    from ollama import Client, ResponseError

    config, brief = load_config(), load_campaign(slug)
    model = config.llm.text_model
    work = WORK_DIR / vid
    candidates = json.loads((work / "candidates.json").read_text(encoding="utf-8"))["candidates"]
    todo = candidates[: top or 2 * config.clips.top_n]
    results = {} if force else load_rerank(vid)
    client = Client(host=OLLAMA_HOST)
    try:
        installed = {m.model for m in client.list().models if m.model}
    except Exception as e:  # serveur arrêté, port fermé…
        raise RuntimeError(f"Ollama injoignable sur {OLLAMA_HOST} : lancer l'application Ollama ({e})") from e
    if model not in installed and f"{model}:latest" not in installed:
        raise RuntimeError(
            f"modèle {model!r} absent d'Ollama : `ollama pull {model}` (installés : {sorted(installed)})"
        )
    try:
        for c in todo:
            if key(c) in results:
                continue
            prompt = PROMPT.format(creator=brief.creator, duration=c["duration"],
                                   reasons=", ".join(c["reasons"]) or "aucun", text=c["text"][:1500])  # fmt: skip
            with steps.step(f"LLM candidat {c['id']}"):
                response = client.chat(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    format=Verdict.model_json_schema(),
                    options={"temperature": 0.2},
                    think=False,
                    keep_alive="5m",
                )
            try:
                verdict = clean(Verdict.model_validate_json(response.message.content or ""))
            except ValidationError as e:
                steps.info(f"candidat {c['id']} : réponse illisible du LLM, ignoré ({e.error_count()} erreur(s))")
                continue
            results[key(c)] = {"id": c["id"], **verdict}
            steps.info(f"#{c['id']} {verdict['score']}/10 — « {verdict['hook']} » — {verdict['reason']}")
            (work / "rerank.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    except ResponseError as e:
        raise RuntimeError(f"erreur Ollama : {e}") from e
    finally:
        with contextlib.suppress(Exception):
            client.chat(model=model, messages=[], keep_alive=0)  # décharge le modèle : rend la RAM
    return work / "rerank.json"


def ordered(candidates: list[dict[str, Any]], rerank: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Avec un rerank : les candidats notés d'abord (score LLM, autonomes en premier), puis les autres dans l'ordre."""

    def rank(c: dict[str, Any]) -> tuple[int, int, int, int]:
        r = rerank.get(key(c))
        if r is None:
            return (1, 0, 0, c["id"])
        return (0, -r["score"], 0 if r["standalone"] else 1, c["id"])

    return sorted(candidates, key=rank)
