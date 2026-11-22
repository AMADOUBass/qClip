"""Ressources par langue des clips (`brief.language`) : gros mots, hashtags génériques, titres par gabarit,
langue demandée au LLM. Tout ce qui dépend de la langue du clip est ici ; l'interface, elle, reste en français.

Langues prévues : « fr » et « en » (tier 1 des campagnes payées au pays : US, Canada, Royaume-Uni…).
Une autre langue retombe sur l'anglais pour le texte, et le filtre de gros mots applique les deux listes.
"""

import re

LANGS = ("fr", "en")
FALLBACK = "en"

# Gros mots : jamais dans une accroche, un titre ni les premières secondes (safety). Les sous-titres restent fidèles.
# Listes séparées : « bite » est un gros mot en français mais un mot courant en anglais (« take a bite »).
_PROFANITY = {
    "fr": r"encul\w*|put(e|ain)\w*|connard\w*|connasse|salop\w*|batard\w*|bâtard\w*|nique\w*|ntm|fdp|merde\w*"
    r"|couilles?|bite|chatte|pd|tg|ta gueule",
    "en": r"fuck\w*|f\*+k\w*|shit\w*|bullshit|bitch\w*|cunt\w*|asshole\w*|motherfuck\w*|dick(head)?s?|pussy"
    r"|cock(sucker)?s?|nigg\w*|fag\w*|retard\w*|whore\w*|slut\w*|bastard\w*|wank\w*|twat\w*|prick\w*",
}
PROFANITY = {lang: re.compile(rf"\b({words})\b", re.IGNORECASE) for lang, words in _PROFANITY.items()}
_ALL = re.compile(rf"\b({'|'.join(_PROFANITY.values())})\b", re.IGNORECASE)

GENERIC_HASHTAGS = {
    "fr": ["#fyp", "#pourtoi", "#twitch", "#clip", "#streamerfr", "#drole"],
    "en": ["#fyp", "#foryou", "#twitch", "#clip", "#gaming", "#funny"],
}

# Titres par gabarit (sans LLM) : citation du clip, sinon réaction tirée des signaux. Jamais de promesse trompeuse.
TITLES = {
    "fr": {"quote": "{creator} : « {quote} »", "bare": "« {quote} »", "laugh": "{creator} en fou rire en live 😂",
           "angry": "{creator} s'énerve en live 😤", "chat": "Le chat de {creator} n'en revient pas 😳",
           "live": "{creator} en live"},
    "en": {"quote": '{creator}: "{quote}"', "bare": '"{quote}"', "laugh": "{creator} can't stop laughing on stream 😂",
           "angry": "{creator} loses it on stream 😤", "chat": "{creator}'s chat can't believe it 😳",
           "live": "{creator} live"},
}  # fmt: skip

# Pour les consignes du LLM (écrites en français) : la langue dans laquelle il doit écrire accroches et titres.
LLM_LANGUAGE = {"fr": "français", "en": "anglais"}


def profanity(lang: str | None) -> re.Pattern[str]:
    """Filtre de la langue du clip ; langue inconnue (None, autre) : toutes les listes."""
    return PROFANITY.get(lang or "", _ALL)


def is_clean(text: str, lang: str | None = None) -> bool:
    return not profanity(lang).search(text)


def hashtags(lang: str) -> list[str]:
    return GENERIC_HASHTAGS.get(lang, GENERIC_HASHTAGS[FALLBACK])


def titles(lang: str) -> dict[str, str]:
    return TITLES.get(lang, TITLES[FALLBACK])


def llm_language(lang: str) -> str:
    return LLM_LANGUAGE.get(lang, LLM_LANGUAGE[FALLBACK])
