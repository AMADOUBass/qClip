"""Clips en anglais (brief.language = « en ») : gros mots, titres, hashtags, mots-clés, sécurité, consignes du LLM."""

import json
from types import SimpleNamespace

import pytest

from qclip.campaign import CAMPAIGNS_DIR, TEMPLATE_NAME, Brief, load_brief
from qclip.config import load_config
from qclip.lang import hashtags, is_clean
from qclip.meta import best_quote, make_caption, make_hashtags, make_hook, make_title
from qclip.safety import events


def brief(**changes: object) -> Brief:
    return load_brief(CAMPAIGNS_DIR / TEMPLATE_NAME).model_copy(update=changes)


def words(text: str, start: float, conf: float = 0.95, step: float = 0.3) -> list[dict]:
    return [{"text": t, "start": start + i * step, "end": start + (i + 1) * step, "confidence": conf}
            for i, t in enumerate(text.split())]  # fmt: skip


def test_profanity_lists_are_per_language() -> None:
    assert not is_clean("What the fuck is that", "en")
    assert not is_clean("This is bullshit!", "en")
    assert is_clean("Take a bite of that", "en")  # « bite » : gros mot en français, mot courant en anglais
    assert not is_clean("Take a bite of that", "fr")
    assert is_clean("Scunthorpe classic match", "en")  # mots entiers seulement
    assert not is_clean("putain", None) and not is_clean("shit", None)  # langue inconnue : toutes les listes


def test_english_titles_hooks_and_hashtags() -> None:
    clip = words("Okay let me focus.", 100.2) + words("Fuck that guy man!", 104.0) + words("No way he did that?", 107.0)
    assert best_quote(clip, 100.0, [], lang="en") == "No way he did that?"  # la phrase grossière est écartée
    assert make_hook(clip, 100.0, ["no way"], "en") == "No way he did that?"
    assert make_title("xQc", "No way he did that?", [], "en") == 'xQc: "No way he did that?"'
    assert make_title("xQc", "", ["chat ×6.0", "rires (0.99)"], "en") == "xQc can't stop laughing on stream 😂"
    assert make_title("xQc", "", ["voix forte"], "en") == "xQc loses it on stream 😤"
    assert make_title("xQc", "", ["chat ×3.1"], "en") == "xQc's chat can't believe it 😳"
    long = make_title("xQc", "this is a very long quote that will never fit inside a sixty character title", [], "en")
    assert len(long) <= 60 and long.startswith('"') and long.endswith("…")
    tags = make_hashtags(brief(language="en", creator="xQc"))
    assert "#foryou" in tags and "#pourtoi" not in tags and "#xqc" in tags  # 5 au total : brief, créateur, génériques
    assert hashtags("en") == ["#fyp", "#foryou", "#twitch", "#clip", "#gaming", "#funny"]
    assert "#pourtoi" in make_hashtags(brief(language="fr"))  # le français ne change pas
    caption = make_caption('xQc: "No way"', brief(language="en", creator="xQc"), tags)
    assert caption.startswith('xQc: "No way"') and "#foryou" in caption


def test_keywords_per_language_from_config() -> None:
    config = load_config()
    assert "wesh" in config.keywords_for("fr") and "no way" in config.keywords_for("en")
    assert config.keywords_for("de") == []


def test_english_profanity_in_first_seconds_is_flagged() -> None:
    found = events(words("Yo what the fuck happened", 100.0), None, None, [], "en")
    assert [e["detail"] for e in found] == ["fuck"]
    assert events(words("Take a bite", 100.0), None, None, [], "en") == []


def test_llm_is_asked_to_write_in_the_clip_language(monkeypatch: pytest.MonkeyPatch) -> None:
    import ollama

    from qclip.rerank import suggest
    from qclip.steps import Steps

    prompts: list[str] = []

    class FakeClient:
        def __init__(self, host: str) -> None: ...
        def list(self):  # noqa: A003
            return SimpleNamespace(models=[SimpleNamespace(model="m")])

        def chat(self, **kw):
            if kw.get("messages"):
                prompts.append(kw["messages"][0]["content"])
            answer = {"hooks": ["He did NOT see that coming", "What the fuck bro"], "title": "xQc: no way"}
            return SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))

    monkeypatch.setattr(ollama, "Client", FakeClient)
    out = suggest("xQc", "no way he did that", 30.0, [], "m", Steps(), "en")
    assert "en anglais" in prompts[0]
    assert out["hooks"] == ["He did NOT see that coming"]  # gros mot anglais filtré
