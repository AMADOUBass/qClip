from pathlib import Path

import pytest

from qclip import posts
from qclip.campaign import CAMPAIGNS_DIR, TEMPLATE_NAME, Brief, load_brief
from qclip.config import ConfigError
from qclip.meta import TEST_BANNER, best_quote, compliance, make_caption, make_hashtags, make_hook, make_title
from qclip.rerank import Verdict, clean, ordered


def brief(**changes: object) -> Brief:
    return load_brief(CAMPAIGNS_DIR / TEMPLATE_NAME).model_copy(update=changes)


def words(text: str, start: float, conf: float = 0.95, step: float = 0.3) -> list[dict]:
    return [
        {"text": t, "start": start + i * step, "end": start + (i + 1) * step, "confidence": conf}
        for i, t in enumerate(text.split())
    ]


# Phrase sûre mais dite pendant l'accroche, phrase vive et sûre, phrase mal reconnue par l'ASR (cas réel).
CLIP = (
    words("Écoute moi bien.", 100.2)
    + words("Maybe like so bad action!", 104.0, conf=0.35)
    + words("T'as vu Daesh au camp?", 107.0)
    + words("Bon on continue la game.", 112.0)
)


def test_best_quote_skips_unreliable_asr() -> None:
    assert best_quote(CLIP, 100.0, keywords=[]) == "T'as vu Daesh au camp?"
    assert make_hook(CLIP, 100.0, keywords=[]) == "T'as vu Daesh au camp?"
    assert make_hook(words("T'es chaud toi?", 100.5), 100.0, []) == ""  # dite pendant l'accroche


def test_make_title_limits() -> None:
    assert make_title("NoahLunsi", "T'as vu Daesh au camp?", []) == "NoahLunsi : « T'as vu Daesh au camp? »"
    long = make_title("NoahLunsi", "on part sur une phrase beaucoup trop longue pour un titre de post", [])
    assert len(long) <= 60 and long.endswith("…")
    assert "fou rire" in make_title("NoahLunsi", "", ["chat ×6.0", "rires (0.99)"])
    assert len(make_title("X" * 80, "", [])) <= 60


def test_hashtags_required_first_and_5_to_8() -> None:
    tags = make_hashtags(brief())
    assert tags[:2] == ["#streamerx", "#gta6"]
    assert 5 <= len(tags) <= 8
    assert len({t.lower() for t in tags}) == len(tags)


def test_caption_and_compliance() -> None:
    b = brief()
    title = "StreamerX : « T'as vu ça? »"
    caption = make_caption(title, b, make_hashtags(b))
    assert caption.startswith(title) and "@streamerx" in caption and "#gta6" in caption
    assert compliance(b, 30.0, caption, title)["ok"]
    report = compliance(b, 70.0, caption.replace("#gta6", ""), title)
    failed = {c["name"] for c in report["checks"] if not c["ok"]}
    assert not report["ok"] and failed == {"durée", "hashtags"}
    test_caption = make_caption(title, brief(test_only=True), [])
    assert test_caption.startswith(TEST_BANNER)
    assert not compliance(brief(test_only=True), 30.0, test_caption, title)["ok"]


def test_llm_verdict_is_cleaned_and_orders_candidates() -> None:
    v = clean(Verdict(score=8, hook="« un deux trois quatre cinq six sept huit neuf »", title="t" * 80,
                      reason="drôle", standalone=True))  # fmt: skip
    assert v["hook"] == "un deux trois quatre cinq six sept huit" and len(v["title"]) <= 60
    cands = [{"id": i, "window": i, "start": float(i), "end": i + 30.0} for i in (1, 2, 3)]
    rerank = {"3:3.000:33.000": {"score": 9, "standalone": True}, "2:2.000:32.000": {"score": 9, "standalone": False}}
    assert [c["id"] for c in ordered(cands, rerank)] == [3, 2, 1]


@pytest.fixture
def campaign(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(posts, "INPUT_DIR", tmp_path)
    monkeypatch.setattr(posts, "load_campaign", lambda slug: brief(rate_per_1k=1.5))
    posts.record_render("demo", {"video_id": "twitch-1", "clip_id": 3, "vod_start": 100.0, "vod_end": 130.0})
    posts.record_render("demo", {"video_id": "twitch-1", "clip_id": 4, "vod_start": 500.0, "vod_end": 528.0})
    return "demo"


def test_log_post_and_stats(campaign: str) -> None:
    posts.log_post(campaign, "3", "tiktok", "https://www.tiktok.com/@moi/video/1", None)
    posts.log_post(campaign, "twitch-1/3", "shorts", "https://youtube.com/shorts/abc", 1200)
    posts.log_post(campaign, "3", "tiktok", None, 20000)  # mise à jour des vues seules
    rows = posts.read_posts(campaign)
    assert len(rows) == 3  # clip 3 sur 2 plateformes + clip 4 (rendu, pas posté)
    s = posts.campaign_stats(campaign)
    assert (s.rendered, s.posted, s.views) == (2, 2, 21200)
    assert s.earnings == pytest.approx(31.8)
    assert posts.posted_ranges(campaign, "twitch-1") == [(100.0, 130.0), (100.0, 130.0)]
    # un nouveau rendu du clip 3 ne touche pas aux lignes déjà postées
    posts.record_render(campaign, {"video_id": "twitch-1", "clip_id": 3, "vod_start": 101.0, "vod_end": 131.0})
    assert all(r["vod_start"] == "100.0" for r in posts.read_posts(campaign) if r["post_url"])


def test_log_post_refusals(campaign: str, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError, match="introuvable"):
        posts.log_post(campaign, "9", "tiktok", "https://x.y/z", None)
    with pytest.raises(ConfigError, match="plateforme inconnue"):
        posts.log_post(campaign, "3", "myspace", "https://x.y/z", None)
    with pytest.raises(ConfigError, match="--url"):
        posts.log_post(campaign, "4", "tiktok", None, 10)
    monkeypatch.setattr(posts, "load_campaign", lambda slug: brief(test_only=True))
    with pytest.raises(ConfigError, match="campagne de test"):
        posts.log_post(campaign, "3", "tiktok", "https://x.y/z", None)


def test_llm_profanity_falls_back_to_templates() -> None:
    title = "NoahLunsi : le loup-garou enculé"
    v = clean(Verdict(score=5, hook="Loup-garou enculé ?", title=title,
                      reason="x", standalone=True))  # fmt: skip
    assert v["hook"] == "" and v["title"] == ""
    ok = clean(Verdict(score=5, hook="Ce que j'ai vu au camp", title="NoahLunsi : Réaction au camp", reason="x",
                       standalone=True))  # fmt: skip
    assert ok["hook"] == "Ce que j'ai vu au camp" and ok["title"] == "NoahLunsi : Réaction au camp"
    assert clean(Verdict(score=5, hook="Il est putain de fort", title="t", reason="x", standalone=True))["hook"] == ""
    assert clean(Verdict(score=5, hook="Computer power", title="t", reason="x", standalone=True))["hook"] != ""


def test_estimate_respects_brief_min_and_max() -> None:
    assert posts.estimate(20000, 1.5, None, None) == 30.0
    assert posts.estimate(2000, 1.5, 5.0, None) == 0.0  # 3 $ < minimum de 5 $ → non payé
    assert posts.estimate(100000, 1.5, 5.0, 75.0) == 75.0  # plafonné


def test_paid_and_budget(campaign: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(posts, "load_campaign", lambda slug: brief(rate_per_1k=1.5, budget_total=100.0, payout_min=5.0))
    posts.log_post(campaign, "3", "tiktok", "https://www.tiktok.com/@moi/video/1", 20000)
    posts.log_post(campaign, "3", "tiktok", None, None, paid=28.5)
    s = posts.campaign_stats(campaign)
    assert s.earnings == pytest.approx(30.0) and s.paid == pytest.approx(28.5)
    assert s.budget_left == pytest.approx(71.5)
    with pytest.raises(ConfigError, match="négatif"):
        posts.log_post(campaign, "3", "tiktok", None, None, paid=-1)


def test_suggest_cleans_llm_proposals(monkeypatch: pytest.MonkeyPatch) -> None:
    """Accroches de l'éditeur : gros mots écartés, doublons retirés, 8 mots max, titre ≤ 60, modèle déchargé."""
    import json
    from types import SimpleNamespace

    import ollama

    from qclip.rerank import suggest
    from qclip.steps import Steps

    calls: list[dict] = []
    answer = {
        "hooks": [
            "Il a rien vu venir",
            "Quel enculé ce chat",
            "il a rien vu venir",
            "un deux trois quatre cinq six sept huit neuf dix",
        ],
        "title": "NoahLunsi " + "très " * 20,
    }

    class FakeClient:
        def __init__(self, host: str) -> None: ...
        def list(self):  # noqa: A003
            return SimpleNamespace(models=[SimpleNamespace(model="qwen3.5:4b-q4_K_M")])

        def chat(self, **kw):
            calls.append(kw)
            return SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))

    monkeypatch.setattr(ollama, "Client", FakeClient)
    out = suggest("NoahLunsi", "texte du clip", 28.0, ["chat ×6.0"], "qwen3.5:4b-q4_K_M", Steps())
    assert out["hooks"] == ["Il a rien vu venir", "un deux trois quatre cinq six sept huit"]
    assert len(out["title"]) <= 60 and out["title"].endswith("…")
    assert calls[0]["keep_alive"] == 0 and calls[-1]["messages"] == []  # déchargé après
    monkeypatch.setattr(FakeClient, "list", lambda self: SimpleNamespace(models=[]))
    with pytest.raises(RuntimeError, match="absent"):
        suggest("NoahLunsi", "t", 20.0, [], "qwen3.5:4b-q4_K_M", Steps())
