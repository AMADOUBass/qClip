# qClip — Spécification (v4, novembre 2026 — profil « portable sans GPU »)

## 0. Objectif
CLI local pour les **campagnes de clipping** (Content Rewards / Whop et équivalents) : on part d'une VOD ou d'une vidéo
d'un **autre créateur** (streamer Twitch/Kick, YouTuber, podcast, GTA 6 RP…) fournie ou autorisée par la campagne,
et on sort en série des clips verticaux 1080x1920 prêts pour Shorts / TikTok / Reels : sous-titres FR mot par mot,
accroche, titre, hashtags, et conformité au brief de la campagne. Payé aux vues : le volume et la qualité comptent.

**Machine cible : portable Windows, processeur Intel, GPU intégré Intel UHD 620, pas de carte Nvidia.**
Donc : tout sur le CPU, modèles légers (ONNX int8), un seul modèle chargé à la fois, encodage vidéo par Intel Quick Sync.
Le code doit rester capable d'utiliser CUDA si un jour la machine en a un (`device: auto`), mais rien ne doit en dépendre.

Pas de cloud par défaut. L'interface web vient au jalon M8 seulement (§7) : en attendant, garder le cœur découplé de la CLI.

Règle absolue : on ne traite que du contenu fourni ou explicitement autorisé par une campagne. Chaque source est liée à une campagne.

---

## 1. Idée centrale : « repérer d'abord, traiter ensuite »
Sur un CPU, transcrire ou séparer 6 h de VOD prendrait des heures. On inverse donc le pipeline :
1. **Repérage (léger)** : on récupère seulement le **chat** et l'**audio basse qualité** de la VOD entière.
   On calcule les signaux pas chers (chat, volume) et on garde les ~3×N meilleures fenêtres de 60–90 s.
2. **Traitement (lourd)** : on télécharge **seulement ces plages vidéo**, et on fait la séparation de la voix,
   la transcription et l'analyse fine **uniquement sur ces fenêtres**.
Résultat : on traite 30–45 min au lieu de 6 h.

---

## 2. Campagnes et sources
- Une campagne = un fichier `campaigns/<slug>.yaml` (le « brief ») :
  ```yaml
  name: "Streamer X — clips GTA 6"
  creator: "StreamerX"
  platforms: [tiktok, shorts, reels]
  rate_per_1k: 1.0            # info, pour mes stats
  sources: ["https://www.twitch.tv/videos/123456789", "https://drive.google.com/..."]
  clip: { min_len: 15, max_len: 59 }
  required: { mention: "@streamerx", hashtags: ["#streamerx", "#gta6"], caption_note: "" }
  forbidden: ["musique ajoutée", "contenu d'une autre campagne"]
  layout: facecam             # facecam | blur | crop
  language: fr
  ```
- Téléchargement : `yt-dlp` (YouTube, Kick, Twitch, liens directs ; audio seul et `--download-sections` pour les plages)
  et **TwitchDownloaderCLI** (binaire dans `tools/`) pour le **replay du chat** Twitch en JSON (et la vidéo par plages).
  Liens Google Drive / Dropbox : téléchargement direct ou dépôt manuel dans `input/<campagne>/`.

---

## 3. Stack retenue (profil CPU)

| Brique | Choix par défaut | Alternatives (bench) | Pourquoi |
|---|---|---|---|
| Projet / deps | `uv`, Python 3.12 (installé par uv) | — | |
| Lint / format / types | `ruff`, `ty` (beta) | Pyright | |
| CLI / config | `typer` + `rich`, `pydantic` + YAML | — | |
| Téléchargement | `yt-dlp` + TwitchDownloaderCLI | — | |
| **Transcription FR** | **Parakeet TDT 0.6B v3 via `onnx-asr`** (int8, CPU) | WhisperX / faster-whisper `small` ou `medium` en int8 ; Qwen3-ASR-0.6B + Qwen3-ForcedAligner | Parakeet v3 = français, timestamps par mot, très rapide sur CPU. Fenêtre max ~20–30 s → découpe par VAD. On confirme avec `qclip bench-asr` |
| VAD | Silero VAD (ONNX) | — | découpe la parole pour Parakeet |
| Séparation de la voix | `audio-separator`, **uniquement sur les fenêtres retenues** ; modèle le plus rapide qui reste propre (bench : MDX-Net léger vs MelBand RoFormer) | désactivable | lent sur CPU : jamais sur la VOD entière |
| Événements audio | CLAP zéro-shot (`transformers`), sur les fenêtres seulement | désactivable | rires, cris, explosions, sirènes |
| Chat | replay JSON de TwitchDownloaderCLI | — | **signal n°1**, quasi gratuit à calculer |
| Coupes de scène | PySceneDetect, sur les fenêtres | — | |
| LLM texte (rerank, titres) | Ollama, petit modèle (ex. `qwen3.5:4b`), **optionnel** | aucun (heuristiques) | lent sur CPU : seulement sur le top 2×N, textes courts |
| Vision (safety) | Ollama, petit modèle avec entrée image (ex. `qwen3.5:4b`), **optionnel** | règle simple + revue humaine | 8 images par clip max |
| Détection visage | OpenCV YuNet, une fois par VOD | rectangle manuel dans le brief | |
| Sous-titres | ASS via `pysubs2`, brûlé par ffmpeg/libass | — | |
| **Encodage** | ffmpeg **`h264_qsv`** (Intel Quick Sync) | `libx264 -preset veryfast -crf 20` si QSV indisponible | le GPU Intel encode bien la vidéo, même s'il ne fait pas d'IA |

Interdit sur cette machine : modèles > ~2B paramètres pour l'audio, séparation ou transcription sur une VOD entière,
deux modèles chargés en même temps.

---

## 4. Pipeline

### 4.1 scout (léger, sur la VOD entière)
- Twitch : `chatdownload` (JSON). Partout : audio seul en basse qualité via yt-dlp (ex. mono 16 kHz après conversion).
- Signaux : messages de chat/s (z-score) + emotes de rire et de choc (liste configurable) + volume RMS (z-score).
  Recaler le chat de −3 à −8 s (les réactions arrivent après le moment).
- Sans chat (YouTube, podcast) : volume + débit de parole estimé par VAD.
- Garder les `scout_windows` meilleures fenêtres (défaut 3×top_n), 60–90 s chacune, sans chevauchement > 30 %,
  en excluant les plages déjà clippées (`posts.csv`).
- → `work/<id>/scout.json`

### 4.2 fetch
- Télécharger **seulement les plages vidéo** des fenêtres (≤ 1080p), avec 5 s de marge de chaque côté.
- → `work/<id>/windows/w_<n>.mp4` + `input/<campagne>/sources.json` (URL, date, plages)

### 4.3 ingest (par fenêtre)
- Audio de la fenêtre → séparation voix / reste (si activée) → `vocals.wav` (mono 16 kHz), `other.wav` (mono 48 kHz).

### 4.4 transcribe (par fenêtre)
- Interface : `Transcriber.transcribe(wav: Path) -> list[Word]` avec `Word(text, start, end, confidence)`, timestamps ramenés au temps de la VOD.
- Backends : `parakeet` (défaut), `whisper` (faster-whisper int8, small/medium), `qwen3`.
- → `work/<id>/windows/w_<n>.transcript.json`

### 4.5 signals fins + candidates
- Sur chaque fenêtre : volume voix/reste, CLAP (si activé), débit de mots, mots-clés FR, coupes de scène.
- Score combiné (poids dans la config ; le chat pèse le plus quand il existe) → meilleur sous-segment de la fenêtre.
- Caler sur une fin de phrase ou une coupe de scène ; ne jamais couper un mot ; longueur dans les bornes du brief.
- → `work/<id>/candidates.json`

### 4.6 rerank (optionnel, `use_llm: true`)
- Top 2×N : extrait de transcription + résumé des signaux → JSON `{score: 0-10, hook: str (≤ 8 mots), reason: str, standalone: bool}`.
- `keep_alive: 0` pour libérer la RAM ensuite.

### 4.7 review
- Tableau rich : rang, début, durée, score, raisons, extrait. Choix des ids. `--auto` prend le top N.

### 4.8 render
- Layouts : `facecam` (défaut streams : facecam en haut ≈ 1/3, jeu en bas ≈ 2/3), `blur`, `crop`.
- Sous-titres : 2 à 4 mots par ligne, mot prononcé surligné, police grasse, contour épais ;
  zones sûres : ni dans les 20 % du bas, ni sur le bord droit, ni sur la facecam.
- Accroche en haut pendant 3 s. Mention du créateur si le brief l'exige.
- Audio : `loudnorm` deux passes, −14 LUFS. Aucune musique ajoutée si le brief l'interdit.
- Légère variation par clip (zoom, couleur des sous-titres) contre la détection de doublons.
- Encodage `h264_qsv`, sinon `libx264 -preset veryfast`. Rendre les clips un par un (pas en parallèle sur ce CPU).
- → `output/<campagne>/<id>/clip_<n>.mp4` + `clip_<n>.jpg`

### 4.9 safety
- Règle YouTube : violence graphique dans les 7 premières secondes = pas de pub ; miniature et titre vérifiés à part.
- Sans LLM vision : signaler les clips dont les 8 premières secondes contiennent des pics « explosion / coups de feu » (CLAP)
  et me demander de vérifier. Avec LLM vision : 8 images (0–7 s + miniature) → JSON `{graphic_violence, gore, confidence}`.
- Vérifier aussi le brief (durée, mention, hashtags, contenu interdit). → `clip_<n>.safety.json`

### 4.10 meta + suivi
- Titre FR (≤ 60 car.), légende avec mention et hashtags du brief → `clip_<n>.json`, `clip_<n>.caption.txt`.
  Sans LLM : gabarits de titres + mots-clés de la transcription.
- `posts.csv` par campagne : clip, source, plage, date, plateforme, URL du post, vues (à la main) → anti-doublon + stats.

---

## 5. CLI
```
qclip doctor
qclip campaign new <slug>
qclip scout <campagne> [--url ...]            # chat + audio léger → fenêtres
qclip process <campagne> [--video <id>] [--auto] [-n 10] [--force]   # scout → fetch → … → render
qclip render <campagne> --video <id> --ids 1,3,5
qclip safety <clip.mp4> [--campaign <slug>]
qclip bench-asr <wav> [--backends parakeet,whisper,qwen3]
qclip bench-sep <wav>                          # compare les modèles de séparation : temps et qualité
qclip log <campagne> <clip> --platform tiktok --url <post>
qclip stats <campagne>
```

## 6. Config globale (`config.yaml`)
```yaml
device: auto                     # auto | cpu | cuda — ici ce sera cpu
threads: auto                    # nb de cœurs physiques
asr: { backend: parakeet, model: nemo-parakeet-tdt-0.6b-v3, quantization: int8 }
separation: { enabled: true, model: "le plus rapide validé par bench-sep" }
scout: { window_len: 75, windows_factor: 3, chat_delay: 5 }
clips: { min_len: 15, max_len: 59, top_n: 8, preroll: 3.0 }
weights: { chat: 2.0, loudness: 1.0, audio_events: 0.8, speech_energy: 1.0 }
chat_emotes: ["KEKW", "LUL", "OMEGALUL", "LMAO", "💀", "W", "PogChamp", "Pog"]
audio_event_labels: ["people laughing", "person screaming", "explosion", "gunshots", "police siren", "car crash"]
keywords: ["oh", "nan", "wesh", "c'est pas possible", "tabarnak", "wallah"]
features: { clap: true, scenes: true }
llm: { use_llm: false, use_vision: false, text_model: "qwen3.5:4b", vision_model: "qwen3.5:4b" }
render: { layout: facecam, fps: 30, encoder: auto, lufs: -14 }
subtitle: { font: "Montserrat ExtraBold", size: 90, color: "#FFFFFF", highlight: "#FFD400", outline: 6, words_per_line: 3, uppercase: true }
```

## 7. Interface de revue (M8)
- **Design** : maquettes faites dans Claude Design, exportées dans `docs/design/`. Les suivre fidèlement ; demander si un écran manque.
- **Backend** : FastAPI local (`qclip serve`, `localhost` uniquement), qui appelle le même cœur Python que la CLI. Tâches longues en arrière-plan, progression par SSE.
- **Frontend** : Next.js (App Router) + TypeScript + Tailwind, dans `web/`. Vidéo servie par l'API (requêtes Range).
- **Écrans** : 1) Campagnes + stats ; 2) VOD : ajout d'URL et progression (scout → fetch → transcription → candidats) ;
  3) Revue des candidats : timeline avec pics, liste avec aperçu, cocher et ajuster début/fin ;
  4) Éditeur de clip : aperçu 9:16, correction des sous-titres, layout, style, accroche, relancer le rendu ;
  5) Prêt à poster : clips, verdict safety, légende copiable, miniature, saisie de l'URL du post.
- ✔ = parcours complet (URL → clips postés et logués) sans terminal.

## 8. Jalons (un par un ; montrer le résultat avant de passer au suivant)
- **M0** : projet uv, `qclip doctor` (CPU, RAM, QSV, libass…), `qclip campaign new`. ✔ = doctor sans ❌.
- **M1** : scout (chat + audio léger) + fetch des plages. ✔ = sur une vraie VOD, 20–30 fenêtres cohérentes avec les pics de chat.
- **M2** : ingest + transcribe (Parakeet) + `bench-asr` + `bench-sep`. ✔ = transcriptions justes, temps mesurés, choix faits.
- **M3** : signaux fins + candidates. ✔ = les 5 meilleurs sont de vrais moments forts (je valide). Tests pytest sur le scoring.
- **M4** : render `facecam` + `blur` + sous-titres + loudnorm (QSV). ✔ = `/verify-clip` OK, sous-titres à ±150 ms.
- **M5** : meta (gabarits) + caption.txt + miniature + `posts.csv` / `log` / `stats` ; rerank LLM en option.
- **M6** : safety + `crop` + lot + variations anti-doublon.
- **M7** : perf : objectif < 30 min de calcul pour une VOD de 4 h avec chat, sur cette machine.
- **M8** : interface de revue (§7), seulement après validation de M4.

## 9. Hors périmètre (pour l'instant)
Publication automatique, multi-utilisateur, hébergement en ligne, SaaS. Plus tard si besoin : un mode « GPU loué » pour les gros volumes.

## 10. Décisions prises (journal)
- **M0, 2026-11-18**
  - Package `qclip/` à la racine du dépôt (disposition plate : `[tool.uv.build-backend] module-root = ""`), backend `uv_build`,
    `requires-python = ">=3.12,<3.13"`, script console `qclip = "qclip.cli:app"`.
  - **torch n'est pas installé en M0** (rien ne l'utilise encore). Il arrivera avec le premier modèle qui en a besoin,
    depuis l'index PyPI par défaut (build CPU sous Windows). Aucun index CUDA.
  - `psutil` ajouté aux dépendances de base : cœurs physiques et RAM (doctor, et plus tard `threads: auto`).
  - Le cœur ne fait aucun affichage : `doctor.run_checks()` renvoie des `Check(name, status, detail, fix, seconds)`,
    `campaign.new_campaign()` / `load_brief()` lèvent `ConfigError` avec un message prêt à afficher. `cli.py` ne fait que présenter.
    Une future API (M8) pourra appeler ces fonctions telles quelles.
  - Validation stricte (`extra="forbid"`) : une clé inconnue (faute de frappe) est une erreur. Dans `config.yaml`, tous les champs
    sont obligatoires. Dans un brief, `sources`, `required`, `forbidden` et `language` (`fr`) ont une valeur par défaut.
    Règles en plus : mention commençant par `@`, hashtags par `#`, sources en `http(s)://`, `min_len < max_len`.
  - Slug de campagne : `^[a-z0-9][a-z0-9-]{0,63}$` (les fichiers commençant par `_` sont réservés, ex. `_template.yaml`).
    Le modèle est validé avant chaque copie, et par `doctor`. Commande en plus : `qclip campaign check <slug>`.
  - `qclip doctor` sort avec le code 1 s'il reste un ❌. Le test d'encodage encode vraiment 1 s de mire 1080x1920 à 30 fps
    (h264_qsv, sinon libx264). Le test libass brûle un vrai sous-titre ASS. Ollama est cherché dans le PATH puis dans
    `%LOCALAPPDATA%\Programs\Ollama`, et son serveur est interrogé via `GET /api/tags`.
  - ffmpeg : build Gyan via winget (inclut libass et QSV/libvpl). Validé avec `Gyan.FFmpeg` 9.0.2 « full » (premier dans le PATH) :
    `h264_qsv` fonctionne sur l'UHD 620 (1 s de 1080x1920 encodée en 1,1 s), libass OK.
