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
from qclip.lang import is_clean, llm_language
from qclip.sources import WORK_DIR
from qclip.steps import Steps

OLLAMA_HOST = "http://127.0.0.1:11434"


class Verdict(BaseModel):
    score: int = Field(ge=0, le=10, description="potentiel viral du clip pour des inconnus qui scrollent, 0 à 10")
    hook: str = Field(
        description="accroche à l'écran, 8 mots maximum, dans la langue demandée, sans mentir sur le contenu"
    )
    title: str = Field(
        description="titre du post, 60 caractères maximum, dans la langue demandée, sans clickbait trompeur"
    )
    reason: str = Field(description="une phrase : pourquoi ce score")
    standalone: bool = Field(description="le clip se comprend-il sans connaître le contexte du live ?")


PROMPT = """Tu es monteur de clips courts (TikTok, Shorts, Reels) pour le streamer {creator}.
Voici un extrait de {duration:.0f} s d'un live, transcrit automatiquement. La transcription contient des erreurs :
un mot qui n'a pas de sens dans la phrase est sûrement mal transcrit, ne le reprends jamais.
Signaux mesurés pendant le live : {reasons}.

Transcription :
\"\"\"{text}\"\"\"

Réponds en JSON :
- score : potentiel pour des inconnus qui scrollent. 0-3 banal, 4-6 correct, 7-8 très bon, 9-10 exceptionnel (rare).
  Un passage confus ou qu'on ne comprend pas sans contexte ne dépasse pas 5.
- hook : accroche affichée à l'écran, 3 à 8 mots, en {langue}, qui donne envie de voir la suite. Aucun gros mot.
- title : titre du post, 60 caractères max, commence par « {creator} » ou par une réaction. Jamais « Live : ».
  N'invente rien qui ne soit pas dans l'extrait. Pas de gros mot.
- reason : une phrase concrète sur ce qui se passe dans l'extrait.
- standalone : true seulement si un inconnu comprend l'extrait sans connaître le live.

L'accroche et le titre doivent parler de CE QUI SE PASSE DANS CET EXTRAIT (pas d'un autre clip), avec tes mots :
ne recopie pas un morceau de transcription confus, résume plutôt la situation ou la réaction."""


def key(c: dict[str, Any]) -> str:
    return f"{c['window']}:{c['start']:.3f}:{c['end']:.3f}"


def load_rerank(vid: str) -> dict[str, dict[str, Any]]:
    """Notes du LLM ; le filtre de gros mots s'applique aussi à la lecture (fichiers écrits avant le filtre)."""
    path = WORK_DIR / vid / "rerank.json"
    data: dict[str, dict[str, Any]] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for verdict in data.values():
        for field in ("hook", "title"):
            if not is_clean(verdict.get(field, "")):
                verdict[field] = ""
    return data


# Gros mots : une accroche ou un titre du LLM qui en contient est ignoré (retour au gabarit) → lang.is_clean.


class Suggestions(BaseModel):
    # Pas de max_length : un modèle qui en renvoie 4 ne doit pas tout faire échouer ; on garde les 3 premières valides.
    hooks: list[str] = Field(min_length=1, description="3 accroches différentes, 3 à 8 mots chacune")
    title: str = Field(description="titre du post, 60 caractères maximum")


# Consigne de l'éditeur, plus stricte que PROMPT : le test du 4B (2026-11-22) inventait à partir des erreurs de
# transcription (« camp de Daesh », « Big Day ») et prêtait des propos négatifs au créateur. Les propositions sont
# montrées à l'utilisateur, qui choisit : rien n'est appliqué sans lui.
SUGGEST_PROMPT = """Tu proposes des accroches pour un clip court (TikTok, Shorts) du streamer {creator}.
Voici ce qu'il dit dans le clip ({duration:.0f} s), transcrit automatiquement (avec des erreurs) :
\"\"\"{text}\"\"\"
Signaux mesurés pendant le live : {reasons}.

Règles strictes :
- Utilise les mots et la situation du texte. N'invente aucun fait, aucun nom, aucun lieu, aucun événement.
- Un mot qui n'a pas de sens dans la phrase est mal transcrit : ignore-le, ne le reprends jamais.
- Ne prête jamais au streamer une insulte, une moquerie ou un propos négatif envers quelqu'un.
- Aucun gros mot. Écris accroches et titre en {langue} correct (la langue du clip).

Réponds en JSON :
- hooks : 3 accroches différentes, 3 à 8 mots, qui donnent envie de voir la suite (question, réaction, situation).
- title : titre du post, 60 caractères max, commence par « {creator} »."""


def suggest(
    creator: str, text: str, duration: float, reasons: list[str], model: str, steps: Steps, lang: str = "fr"
) -> dict[str, Any]:
    """Accroches et titre proposés par le LLM pour un moment (éditeur, à la demande). Modèle déchargé ensuite."""
    from ollama import Client, ResponseError

    client = Client(host=OLLAMA_HOST)
    try:
        installed = {m.model for m in client.list().models if m.model}
    except Exception as e:  # serveur arrêté, port fermé…
        raise RuntimeError(f"Ollama injoignable sur {OLLAMA_HOST} : lancer l'application Ollama ({e})") from e
    if model not in installed and f"{model}:latest" not in installed:
        raise RuntimeError(f"modèle {model!r} absent d'Ollama : `ollama pull {model}`")
    prompt = SUGGEST_PROMPT.format(creator=creator, duration=duration, text=text[:1500], langue=llm_language(lang),
                                   reasons=", ".join(reasons) or "aucun")  # fmt: skip
    try:
        with steps.step(f"propositions d'accroche ({model})"):
            response = client.chat(model=model, messages=[{"role": "user", "content": prompt}],
                                   format=Suggestions.model_json_schema(), options={"temperature": 0.4},
                                   think=False, keep_alive=0)  # fmt: skip
    except ResponseError as e:
        raise RuntimeError(f"erreur Ollama : {e}") from e
    finally:
        with contextlib.suppress(Exception):
            client.chat(model=model, messages=[], keep_alive=0)  # décharge le modèle : rend la RAM
    try:
        raw = Suggestions.model_validate_json(response.message.content or "")
    except ValidationError as e:
        raise RuntimeError(f"réponse illisible du modèle ({e.error_count()} erreur(s)) : réessayer") from e
    hooks: list[str] = []
    for h in raw.hooks:
        h = " ".join(h.strip().strip('"«»').split()[:8])
        if h and is_clean(h, lang) and h.lower() not in {x.lower() for x in hooks} and len(hooks) < 3:
            hooks.append(h[:80])
    title = raw.title.strip().strip('"«»')
    title = title if len(title) <= 60 else title[:59].rsplit(" ", 1)[0] + "…"
    return {"hooks": hooks, "title": title if is_clean(title, lang) else "", "model": model,
            "seconds": round(steps.timings.get(f"propositions d'accroche ({model})", 0.0), 1)}  # fmt: skip


def clean(verdict: Verdict, lang: str | None = None) -> dict[str, Any]:
    hook = " ".join(verdict.hook.strip().strip('"«»').split()[:8])
    title = verdict.title.strip().strip('"')
    title = title if len(title) <= 60 else title[:59].rsplit(" ", 1)[0] + "…"
    # Vide = « pas de proposition » : `qclip render` retombe alors sur l'accroche / le titre par gabarit.
    return {
        **verdict.model_dump(),
        "hook": hook if is_clean(hook, lang) else "",
        "title": title if is_clean(title, lang) else "",
    }


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
            prompt = PROMPT.format(creator=brief.creator, duration=c["duration"], langue=llm_language(brief.language),
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
                verdict = clean(Verdict.model_validate_json(response.message.content or ""), brief.language)
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
