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
qclip safety <campagne> [--video <id>] [--ids 1,3]   # risque de démonétisation des clips rendus (M6)
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
- **Frontend** (dans `web/`, vérifier chaque lib avec Context7 avant usage) :
  - Next.js 16 (App Router, Turbopack) + React 19 + TypeScript strict
  - Tailwind CSS v4 (config dans le CSS via `@theme`) + shadcn/ui (composants copiés, accessibles) + lucide-react (icônes)
  - Motion (ex-Framer Motion) pour les animations et transitions ; sonner pour les notifications
  - TanStack Query (données de l'API, progression) + Zustand (état local de l'éditeur)
  - React Hook Form + Zod (formulaire de brief, mêmes règles que le pydantic côté Python)
  - **Remotion Player** pour l'aperçu 9:16 **en direct** dans l'éditeur (sous-titres, overlay, layout, accroche
    rendus dans le navigateur sans attendre ffmpeg) ; le rendu final reste fait par ffmpeg côté Python.
    Licence gratuite pour un individu (à revérifier si l'équipe dépasse 3 personnes).
  - wavesurfer.js (+ plugin Regions) pour la timeline audio et les poignées début/fin
  - Vidéo servie par l'API (requêtes Range). Tests : Vitest + Playwright.
- **UX** : clavier d'abord (J/K pour naviguer, Espace pour lire, A garder, X rejeter, Ctrl+K palette de commandes),
  animations courtes et utiles, aucune attente sans indicateur de progression ni temps estimé.
- **Écrans** (le détail visuel vient des maquettes) : 1) Tableau de bord + campagnes ; 2) Brief de campagne ;
  3) VOD : « radar » de la VOD entière et progression repérage → traitement ;
  4) Tri des moments (clavier, aperçu instantané) ; 5) Éditeur de clip avec aperçu Remotion en direct ;
  6) Pipeline des clips (À revoir → Rendu → Posté → Payé) avec légende copiable, checklist du brief et saisie des URLs.
- ✔ = parcours complet (URL → clips postés et logués) sans terminal.

## 8. Jalons (un par un ; montrer le résultat avant de passer au suivant)
- **M0** : projet uv, `qclip doctor` (CPU, RAM, QSV, libass…), `qclip campaign new`. ✔ = doctor sans ❌.
- **M1** : scout (chat + audio léger) + fetch des plages. ✔ = sur une vraie VOD, 20–30 fenêtres cohérentes avec les pics de chat.
- **M2** : ingest + transcribe (Parakeet) + `bench-asr` + `bench-sep`. ✔ = transcriptions justes, temps mesurés, choix faits.
- **M3** : signaux fins + candidates. ✔ = les 5 meilleurs sont de vrais moments forts (je valide). Tests pytest sur le scoring.
- **M4** : render `facecam` + `blur` + sous-titres + loudnorm (QSV). ✔ = `/verify-clip` OK, sous-titres à ±150 ms.
- **M5** : meta (gabarits) + caption.txt + miniature + `posts.csv` / `log` / `stats` ; rerank LLM en option.
- **M6** : safety + `crop` + lot + variations anti-doublon. ✔ 2026-11-21.
- **M7** : perf : objectif < 30 min de calcul pour une VOD de 4 h avec chat, sur cette machine. ✔ 2026-11-21 (21,1 min réseau compris).
- **M8** : interface de revue (§7), seulement après validation de M4. ✔ 2026-11-21 (étapes 1 à 7).

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
- **M1, 2026-11-18**
  - Campagne de test : champ de brief `test_only: true` (défaut `false`). Traitement local permis, mais le rendu final
    et la meta (M4-M5) devront refuser de produire des clips « prêts à poster ». Exemple : `campaigns/test-fr.yaml`.
  - Une URL n'est traitée que si elle figure dans `sources` du brief (`campaign.check_source`), y compris avec `--url`.
    Les liens Drive / Dropbox sont ignorés par le scout (dépôt manuel).
  - Médias : **yt-dlp pour tout** (audio du scout + plages vidéo), TwitchDownloaderCLI **seulement pour le chat**
    (un seul chemin de code pour Twitch, YouTube, Kick). TwitchDownloaderCLI 1.56.5 dans `tools/` (SHA-256 vérifié).
  - Identifiant de vidéo : `twitch-<id VOD>` (sans réseau), sinon `<extractor>-<id>` donné par yt-dlp.
  - Scout : signaux à 1 s ; volume RMS (dBFS) calculé en flux par ffmpeg à 8 kHz (jamais toute la VOD en RAM) ;
    chat = messages/s recalés de −`chat_delay` s, un message avec emote compte `1 + emote_bonus` (nouveau paramètre
    `scout.emote_bonus`, défaut 1.0). Lissage (chat 5 s, volume 3 s), z-score glissant sur 10 min, somme pondérée
    (`weights.chat`, `weights.loudness`), lissage 5 s. Sans chat : volume seul (le débit de parole par VAD viendra en M2).
  - Fenêtres : glouton sur les pics, pic placé à 60 % de la fenêtre (contexte avant, réaction après), recouvrement ≤ 30 %,
    `windows_factor × top_n` fenêtres (24 par défaut). L'exclusion des plages déjà clippées (`posts.csv`) attend M5.
  - Fetch : nouvelle commande `qclip fetch <campagne> [--video] [--max-height] [--force]` (absente de §5).
    Plages avec 5 s de marge, **sans réencodage** (`force_keyframes_at_cuts=False`, coupe au keyframe). Le vrai début
    de chaque plage est retrouvé par corrélation croisée de son audio avec l'audio du scout (8 kHz, ± 10 s) →
    `work/<id>/windows/windows.json` (`start` exact, `sync_quality`). Sous 0,5 d'accord, on garde le début demandé.
- **M2, 2026-11-19** (bench sur un extrait de 30 s d'un stream Just Chatting FR, i7-8550U, 4 cœurs)
  - Nouvelles commandes : `qclip ingest <campagne> [--top] [--separation/--no-separation]`,
    `qclip transcribe <campagne> [--top] [--backend]`, `qclip bench-asr <audio> [--backends]`, `qclip bench-sep <audio> [--models]`.
  - **ASR retenu : Parakeet TDT 0.6B v3 int8 (onnx-asr) + Silero VAD**, segments ≤ 20 s. RTF 0,24-0,32, chargement 4-7 s,
    ponctuation, confiance par mot (exp de la moyenne des logprobs). Mots = tokens regroupés (espace initiale = nouveau mot),
    fin d'un mot bornée (dernier token + 0,4 s, et début du mot suivant).
    - Whisper small int8 (faster-whisper) : RTF 0,46, moins juste (« comme nous » au lieu de « au camp de nous »), invente
      des phrases sur l'audio confus. Reçoit l'audio en tableau numpy : faster-whisper 1.2.1 est incompatible avec PyAV 19.
    - Qwen3-ASR-0.6B + ForcedAligner (extra optionnel `uv sync --extra qwen`, float32) : texte de bonne qualité mais
      RTF 6,4 + 38 s de chargement → inutilisable sur ce CPU. ASR puis aligneur chargés l'un après l'autre (jamais ensemble).
      L'extra fait descendre `huggingface-hub` en 0.36 pour tout le projet (sans effet constaté sur onnx-asr).
  - **Séparation de la voix désactivée par défaut** (`separation.enabled: false`) : RTF 2,1 (UVR-MDX-NET-Voc_FT),
    2,8 (Kim_Vocal_2), 5,0 (MelBand RoFormer), sans gain mesurable sur la transcription de cet extrait
    (confiance Parakeet 0,84 sur l'audio brut). Si activée : `UVR-MDX-NET-Voc_FT.onnx`. **À rebencher sur une VOD GTA**
    (musique / bruits de jeu), où elle peut devenir utile. Modèles dans `models/audio-separator/`.
    `audioread` ajouté à la main : audio-separator 0.48 l'importe sans le déclarer (librosa 1.0 ne le tire plus).
  - Sans séparation, `other.wav` = l'audio complet (mono 48 kHz) : c'est ce que CLAP écoutera en M3.
  - Transcriptions : `work/<id>/windows/w_<n>.transcript.json`, mots en **temps de la VOD** + `window_start`
    (temps dans le fichier de la plage = `start - window_start`). Le prompt (nom du créateur) ne sert qu'à Whisper.
- **M3, 2026-11-19**
  - Nouvelle commande `qclip candidates <campagne> [--video] [--clap/--no-clap] [--scenes/--no-scenes] [--force]`
    (remplace `qclip score` : calcule les signaux fins, choisit un passage par plage, affiche le tableau de revue §4.7).
  - Signaux fins sur une grille de 0,5 s, en cache par plage (`w_<n>.signals.npz`, `w_<n>.clap.npy`) :
    chat (z du scout, déjà recalé), volume de la voix, CLAP (max des libellés d'événements), parole
    (débit mots/s + 2 × mots-clés + exclamations). **Normalisation commune à toutes les plages** (z « poolé ») :
    chaque plage est comparée au niveau habituel de la VOD, pas à elle-même.
  - CLAP : `laion/clap-htsat-unfused`, extraits de 4 s tous les 3 s (RTF ≈ 0,11), libellés « de fond » ajoutés
    (parole calme, musique, silence, jeu) pour que le softmax ne désigne pas toujours un événement.
    Sur ce stream, « people laughing » a un niveau de base élevé (≈ 0,76) : seul l'écart à ce niveau compte.
  - Coupes de scène : **filtre `scdet` de ffmpeg** (10 i/s, image 320 px, `-skip_loop_filter all`) au lieu de
    PySceneDetect : même principe, décodage natif plus rapide, pas de dépendance. 12,5 s par plage de 85 s.
    Le décodage QSV échoue sur ce PC (« MFX session -9 ») alors que l'encodage QSV marche.
  - Passage choisi (`score.choose_segment`) : pic du score lissé sur 3 s → début = phrase en cours à « pic − preroll »,
    fin = première fin de phrase après « retombée sous 35 % du pic + 2,5 s » ; trop court → phrases ajoutées avant
    (contexte) puis après ; trop long → phrases retirées au début (sans dépasser le pic) puis fin à une fin de phrase ;
    marge de 0,15 s sans mordre sur un mot voisin ; coupe de scène à moins d'1 s d'une borne = nouvelle borne.
    Frontière de phrase = ponctuation finale ou pause ≥ 0,6 s.
  - Score d'un candidat = moyenne du score combiné à ± 2 s du pic. Doublons > 30 % de recouvrement supprimés.
  - Raisons affichées : chat ×N (activité autour du pic / moyenne de la VOD), événements CLAP ≥ 0,5, voix forte,
    mots-clés, exclamations, débit rapide.
  - Sur la VOD de test : 24 candidats en 7 min 20 (coupes ≈ 5 min, CLAP ≈ 2 min), aucun mot coupé, 24/24 en début
    de phrase, durées 16-22 s avec preroll 3 s. **Preroll passé à 8 s** (demande) : 16-24 s, médiane 19 s ; le début
    était déjà ramené au début de phrase, c'est la fin (retombée + 2,5 s) qui limite la longueur.
  - Fin des clips : 5 s gardées après la retombée (au lieu de 2,5 s) → 15-28 s, médiane 20 s. Pour des clips de
    30 s et plus, il faudra une durée cible (non fait).
- **M4, 2026-11-19**
  - `qclip render <campagne> [--ids 1,3] [--top N] [--layout] [--hook] [--force]`. Un clip = une passe de mesure
    loudnorm + un seul passage ffmpeg (layout + sous-titres + audio). Encodage `h264_qsv` (`-global_quality 23`),
    repli libx264 si le test d'encodage QSV échoue. ≈ 12 s de calcul par clip de 20 s sur ce PC.
  - **Facecam détectée par clip, pas par VOD** : le streamer change de scène (caméra plein cadre, partage d'écran,
    match avec webcam incrustée). YuNet `2026may` (entrée dynamique, requis par OpenCV 5.1), pleine résolution,
    3 images par clip. Règles (validées sur 8 vrais clips) : visage ≥ 10 % de la largeur → `fullcam` ; sinon visage
    de 24-200 px, stable sur ≥ 2 images, **dans un coin** (25 % ext. en x ET 30 % ext. en y), bonus s'il bouge →
    webcam incrustée ; sinon grand visage vu une fois → `fullcam`. YuNet trouve aussi les visages du contenu
    (arbitre, vidéo) et du décor (posters) : d'où le coin et le mouvement. Zone webcam ≈ 7 × la largeur du visage.
    Champ de brief optionnel `facecam: [x, y, w, h]` pour forcer la zone.
  - Layout `facecam` sur une caméra plein cadre (ou sans webcam) → **repli sur `blur`** avec un message. `crop` → M6.
  - Géométrie 1080x1920 : facecam = webcam 1080x640 en haut + bande centrale du jeu 1080x1280 en bas ;
    blur = fond flouté (calculé en 270x480 puis agrandi) + image 1080x608 au centre. Zone interdite : y > 1536
    (20 % du bas) et 150 px à droite. Sous-titres : sous l'image (blur, y ≈ 1400) ou dans le jeu (facecam, y ≈ 1237).
  - Sous-titres ASS (pysubs2) : un événement par mot, mot prononcé en `highlight`, 3 mots par ligne max, coupure
    en fin de phrase, après une virgule (si ≥ 2 mots) ou sur une pause ≥ 0,6 s ; ligne tenue 0,4 s après son dernier mot.
    Police **Montserrat ExtraBold** fournie dans `assets/fonts/` (licence OFL) via `fontsdir`.
  - `clip_<n>.words.tsv` à côté de chaque clip : **corriger le texte à la main puis relancer `render --force`**
    (le fichier existant est réutilisé) → correctif des fautes de transcription en attendant l'éditeur (M8).
  - Accroche provisoire (en attendant M5) : première phrase courte (2-8 mots), de préférence avec ? ou !, dite après
    les 3 premières secondes. Souvent mauvaise (reprend les fautes d'ASR) → `--hook` pour l'imposer.
  - Mention du brief (`required.mention`) affichée en bas à gauche, au-dessus de la zone interdite.
  - **Campagne `test_only`** : rendus dans `work/<id>/renders/` (pas `output/`) avec le bandeau « TEST — NE PAS POSTER ».
  - Audio : loudnorm 2 passes, −14 LUFS, TP −1,5 dB, AAC 192 kb/s 48 kHz. Mesuré sur 8 clips : −13,8 à −15,0 LUFS.
  - **Durée cible** `clips.target_len: 30` (demande) : après le choix du passage, on ajoute des phrases entières
    (avant ou après, celle qui rapproche le plus de la cible), avant seulement si le pic reste dans la 1re moitié de la
    cible ; arrêt à 3 s de la cible, jamais au-delà de `max_len` du brief. Top 8 de la VOD de test : 27-32 s, pic
    9-13 s après le début.
  - `clip_<n>.words.tsv` mémorise le passage (`# passage <début> <fin>`, temps VOD) : il n'est réutilisé que pour le
    même passage. Si le candidat change (nouveaux réglages), il est régénéré et l'ancien gardé en `.tsv.old`
    (sinon les sous-titres seraient décalés — bug trouvé et corrigé pendant M4).
- **M5, 2026-11-20**
  - Après chaque rendu : `clip_<n>.json` (titre, accroche, hashtags, mention, miniature, source, conformité),
    `clip_<n>.caption.txt` (prête à coller), `clip_<n>.jpg`, et une ligne dans `input/<campagne>/posts.csv`.
    `qclip meta <campagne> [--ids]` refait tout ça sans réencoder la vidéo.
  - **Sans LLM (défaut)** : accroche et titre = citation du clip, retenue seulement si l'ASR est sûr de ses mots
    (confiance moyenne ≥ 0,75, aucun mot < 0,45), 2-8 mots (10 pour le titre), de préférence avec ? ou !, dite après
    les 3 premières secondes pour l'accroche. Sinon gabarit tiré des signaux (« … en fou rire en live 😂 »), jamais
    de promesse que les signaux ne justifient pas. Titre ≤ 60 caractères. Pas de citation fiable → pas d'accroche.
  - Hashtags : ceux du brief d'abord, puis `#<créateur>` et des génériques FR, 5 à 8 au total.
  - Conformité (`compliance`) : durée dans les bornes du brief, mention et hashtags exigés présents dans la légende,
    titre ≤ 60, pas de musique ajoutée, campagne réelle. Le reste (contenu interdit, violence) → safety (M6).
  - **Miniature propre** : image la plus nette (variance du laplacien, ± 3 s autour du pic) prise dans la **source**
    et passée par le même layout, **sans sous-titres ni accroche** (le texte incrusté faussait la mesure et pouvait
    afficher une faute d'ASR).
  - Suivi `input/<campagne>/posts.csv` : une ligne par clip rendu, puis une par plateforme postée
    (`qclip log <campagne> <clip> --platform tiktok --url … [--views N]`, vues à mettre à jour avec `--views` seul).
    `qclip stats <campagne>` : rendus, posts, vues, gains ≈ vues / 1000 × `rate_per_1k`. Écriture atomique.
  - **Anti-doublon** : les passages déjà postés (lignes avec URL) sont masqués au scout et écartés des candidats
    (recouvrement > 30 %).
  - **Campagne `test_only`** : légende préfixée « ⚠️ TEST — NE PAS POSTER », conformité en échec, `qclip log` refusé.
  - Rerank LLM (optionnel, `qclip rerank`) : Ollama (`llm.text_model`), sortie JSON imposée par un schéma pydantic
    (score 0-10, accroche ≤ 8 mots, titre ≤ 60, raison, `standalone`), top 2×N, résultats dans `work/<id>/rerank.json`
    (clé = passage, survit à un recalcul des candidats), modèle déchargé à la fin (`keep_alive=0`). `qclip render`
    prend alors les N meilleurs selon le LLM et ses accroches / titres.
  - **Test du rerank (2026-11-20)** avec `qwen3.5:2b-q4_K_M` (1,9 Go, ~22 s par candidat, 8 candidats ≈ 2 min 45) :
    fonctionne, mais **n'apporte rien par rapport aux gabarits** — notes instables d'un essai à l'autre, accroches
    vagues ou recopiées de la transcription, recopie des exemples de la consigne (titre d'un autre clip → trompeur).
    Consigne resserrée (échelle de notes, pas de gros mots, jamais « Live : », pas d'exemple recopiable) : notes plus
    réalistes (3-7), qualité des textes toujours insuffisante. **`use_llm: false` reste le défaut.**
    Garde-fou : accroche / titre du LLM contenant un gros mot → ignorés, retour au gabarit (`rerank.PROFANITY`).
    À retester avec un modèle plus gros (`qwen3.5:4b`, 3,3 Go) si la RAM le permet (8 Go ici, ~2 Go libres).
- **M8 — étape 1 (cœur + API), 2026-11-20**
  - Fonctions de M6 visibles dans les maquettes (alerte démonétisation, layout Recadrage, variation anti-doublon) :
    **affichées mais grisées « disponible en M6 »** (choix de l'utilisateur : « la meilleure solution »).
  - **Brief étendu** (tous les champs optionnels, les anciens briefs restent valides) : `brief_url`, `source_platform`,
    `channel`, `source_rule`, `budget_total`, `payout_min` / `payout_max` (par clip), `overlay` {file, x, y, width}
    (image dans `campaigns/assets/<slug>/`, **incrustée au rendu sous les sous-titres**), `requirements`
    (lien en bio, compte dédié, description liée, délai de soumission), `audience`. `save_brief` écrit le YAML
    validé (les commentaires sont perdus quand l'interface enregistre).
  - `posts.csv` : colonnes `paid` / `paid_at` (`qclip log --paid`). Gain estimé par post = vues / 1000 × tarif,
    **0 sous `payout_min`**, plafonné à `payout_max`. Budget restant = budget − payé.
  - `work/<id>/edits.json` (clé = numéro de plage, stable) : décision du tri (keep / reject / skip), bornes ajustées
    (recalées pour ne jamais couper un mot), layout, style, accroche, **corrections de mots** (clé = début VOD du mot).
    `qclip render --kept` rend les moments gardés ; sans `--ids`, les rejetés sont exclus.
  - **Corrections : l'éditeur est la seule source** ; `clip_<n>.words.tsv` devient un fichier de sortie régénéré
    (la fusion avec des corrections faites à la main dans le TSV réinjectait d'anciennes corrections — bug corrigé).
  - Styles de sous-titres (`subtitle.style`, réglable par clip) : `neon` (mot coloré), `box` (bloc jaune, texte noir),
    `outline` (contour coloré), `karaoke` (remplissage `\kf` au fil de la voix).
  - Gros mots (`meta.PROFANITY`) : jamais dans une accroche ni un titre, ni par gabarit ni par LLM (aussi à la lecture
    des anciens `rerank.json`). Les sous-titres restent fidèles à la parole.
  - `qclip process <campagne>` : chaîne complète (scout → fetch → ingest → transcribe → candidates), étapes annoncées.
  - `qclip serve` (FastAPI, **127.0.0.1:8766 uniquement**) : routes de lecture (`overview.py`, aucune logique dans
    l'API), écriture (brief, overlay, ajout de VOD = ajout aux sources du brief + analyse, réglages, corrections,
    rendu, log), médias sous `/media/` limités à `work/`, `output/`, `campaigns/assets/` (Range : 206), file de tâches
    (`jobs.py`, **une à la fois**, étape / « N/total » / temps restant / journal), état en direct sur `/api/events` (SSE).
  - Score affiché dans l'interface = score des signaux ramené sur 10 (meilleur moment = 10) ; la note du LLM, si
    elle existe, est affichée à part (le 2B n'est pas fiable).
- **M8 — étape 2 (squelette du front), 2026-11-20**
  - `web/` : Next.js 16.4 (App Router, Turbopack, `cacheComponents`), React 19.3, TypeScript strict, Tailwind 4.3,
    shadcn 4 (Radix, préréglage « nova », icônes lucide), TanStack Query 5, Zustand 5, Motion 14, sonner,
    React Hook Form + Zod, Playwright + Vitest. pnpm.
  - **Charte des maquettes** dans `web/app/globals.css` (variables CSS + `@theme inline`) : fond crème `#f2f0eb`,
    cartes `#faf9f6`, jaune `#ffd60a` (action, sélection), bleu `#3b4bf5` (chat, progression), olive `#8a6d00`
    (montants), rose `#d61f4f` (rejet), orange `#e8860c` (alertes), arrondis 28 px. Clair uniquement.
    **Polices (approximation, pas de notes de style fournies)** : Unbounded (titres larges), Inter (texte),
    JetBrains Mono (étiquettes en capitales). À remplacer si les polices exactes de Claude Design sont connues.
  - Données : client `web/lib/api.ts` (API `NEXT_PUBLIC_QCLIP_API`, défaut http://127.0.0.1:8766), état des tâches
    en direct par **EventSource** sur `/api/events` → cache TanStack `["jobs"]` ; une tâche terminée fait recharger
    les écrans. Pastille de tâche dans l'en-tête (étape, « N/total », temps restant).
  - Palette **Ctrl K** (maquette 8) + raccourcis globaux : Ctrl N nouvelle VOD, T trier, Ctrl R rendre les gardés,
    Ctrl ⇧ C copier la dernière légende (pas quand on tape dans un champ).
  - Next 16 (`cacheComponents`) : pas de `new Date()` au rendu d'un composant client → `useNow()`
    (`useSyncExternalStore`). `agentRules: false` (pas d'AGENTS.md), indicateur de dev en bas à droite.
  - Tests e2e `web/e2e/` (API + front lancés) : chaque écran s'affiche sans erreur console, palette Ctrl K.
- **M8 — étape 3 (accueil, campagnes, brief, états), 2026-11-20**
  - **Accueil** (maquette 1) : cartes chiffrées (gains 7 j + courbe, vues vérifiées, moments à trier, prêts à poster),
    carte « En cours sur ta machine » (étapes de la tâche, radar du chat de la VOD, temps restant, RAM), campagnes
    actives, derniers clips (vignette propre + statut). La barre de budget n'apparaît que si le brief a un budget.
  - **Campagnes + brief** (maquette 2) : un seul formulaire pour créer (`/campaigns/new`) et modifier
    (`/campaigns/<slug>`), React Hook Form + Zod (`web/lib/brief-schema.ts`), erreurs en rouge sous chaque champ.
    Écrit `campaigns/<slug>.yaml` via l'API (slug tiré du nom). Overlay PNG/WebP envoyé dans
    `campaigns/assets/<slug>/` et placé en le glissant sur l'aperçu 9:16 (x, y, largeur en fraction de l'image).
    Checklist « avant de poster » calculée en direct depuis le brief.
  - **Ajouts hors maquette** (nécessaires au rendu) : champs « Créateur » (nom dans les titres) et « Mention
    obligatoire ». « Recadrage » est grisé « Disponible en M6 ».
  - **États** (maquette 7) : aucune campagne → lien « Trouver une campagne » vers https://whop.com/discover/ ;
    tâche en erreur → carte avec « Réessayer » et la commande de mise à jour de yt-dlp à copier ; API arrêtée →
    commande `uv run qclip serve`. « Importer un fichier » grisé (pas encore prévu).
  - Next 16 : `usePathname`/`useParams` sous un `<Suspense>` (posé dans le layout).
  - Tests e2e ajoutés (`web/e2e/brief.spec.ts`, rien n'est écrit) : erreurs du brief, hashtag vide ignoré,
    glisser l'overlay. La création complète d'une campagne a été vérifiée à la main puis le fichier de test supprimé.
- **M8 — étape 4 (VOD : radar et traitement), 2026-11-20**
  - `/vod/<id>` (maquette 3) : pastilles (plateforme, langue, durée, messages, règle de source), **radar du hype**
    (chat vers le haut, volume vers le bas, zones en jaune numérotées, numéros décalés d'une ligne quand deux zones
    sont proches), carte « 1 · Repérage » (sous-étapes et temps), carte « 2 · Traitement des zones » (étape en cours :
    « N/total », barre, temps restant ; suivantes : estimation), carte « Temps restant estimé », grille des zones.
    Progression en direct par SSE + relecture de l'état disque toutes les 4 s pendant l'analyse.
  - **Numéro de zone = rang** (#01 = la plus forte), comme partout ailleurs (fichiers `w_01…`, tri, éditeur) ; la
    maquette numérote dans l'ordre du temps. Les zones sont traitées dans l'ordre des rangs.
  - **Écart à la maquette** : « Les 9 premiers moments sont déjà prêts » n'existe pas — le pipeline va étape par
    étape et les moments n'existent qu'après la détection. La carte jaune dit combien de zones sont transcrites et
    le bouton « Trier » s'active à la fin (ou tout de suite si une analyse précédente a déjà des moments).
  - `/vod` : l'analyse en cours, sinon la dernière VOD repérée. `/vod/new` (`?campaign=<slug>` depuis le brief) :
    choix de la campagne, **règle de source à confirmer** avant « Analyser », URL Kick / Twitch / YouTube vérifiée.
  - Cœur : `Steps.video(id)` annonce la VOD dès le repérage (l'écran s'ouvre aussi pour Kick/YouTube) ; durées des
    grandes étapes et des zones vraiment traitées dans `work/<id>/timings.json` ; une reprise depuis le cache
    n'écrase plus les vrais temps (repérage compris). Estimations = médiane des zones mesurées sur cette machine,
    sinon ordres de grandeur (téléchargement 10 s, extraction 2 s, séparation 160 s, transcription 22 s, détection
    10 s par zone de 75 s).
  - **Bug corrigé** (présent depuis M3) : relancer `process` sur une VOD déjà traitée plantait (`find_output` prenait
    `w_01.clap.npy` pour la vidéo). Ne retient plus que `<stem>.<ext>`.
  - Validé en réel depuis l'interface : nouvelle VOD → Analyser → écran VOD en direct jusqu'à « 24 moments »
    (3 zones re-transcrites, transcriptions et candidats identiques à l'original).
- **M8 — étape 5 (tri des moments), 2026-11-21**
  - `/sort?vod=<id>&w=<plage>` (maquette 4) : un moment à la fois, du score le plus haut au plus bas ; « Moment N / total »,
    vidéo de la plage lue **seulement entre le début et la fin du passage** (Espace), score sur 10, horodatage VOD,
    durée ; forme d'onde de toute la plage avec le passage en jaune et **deux poignées** (bornées par la durée min /
    max du brief), clic pour se placer ; raisons en pastilles (« Pic de chat ×6,0 », « Rires »…) ; texte du passage.
  - Clavier : **A** garder, **X** rejeter, **J / K** précédent / suivant, **Espace** lire, **[ ]** début / fin à la tête de
    lecture. « Passer » = décision `skip` (compte comme restant). Après une décision, on saute au prochain moment non
    décidé ; l'affichage n'attend pas l'API (mise à jour immédiate du cache, rechargée ensuite).
  - Bornes : enregistrées dans edits.json, **recalées sur les mots** par le cœur à la lecture (`apply_edit`).
  - Colonne de droite : progression (gardés / rejetés / restants, une case par moment, cliquable) et « Ensuite » :
    les 4 prochains moments non décidés avec une **image au pic** (`GET /api/vods/<id>/moments/<plage>/frame`, ffmpeg,
    320 px, en cache `w_XX.frame.jpg`), l'accroche (rerank) ou les premiers mots.
  - « Rendre les N moments gardés » (dès qu'il y en a un) et **Ctrl R** (palette → `?render=kept`, confirmation
    avant de lancer) → `POST /api/vods/<id>/render {kept: true}`.
- **M8 — étape 6 (éditeur de clip), 2026-11-21**
  - `/editor?vod=<id>&w=<plage>` (maquette 5) : transcription cliquable, aperçu 9:16 en direct, layout, style des
    sous-titres, accroche, « Rendre le clip », ligne de temps ; navigation entre les clips **gardés** (sinon tous).
  - **Aperçu sans Remotion** : la vidéo de la plage est dessinée sur un canvas (540 x 960) avec les mêmes découpes
    que les filtres ffmpeg (blur : fond 9:16 flou + image 16:9 centrée ; facecam : webcam 1080 x 640 en haut, bande
    centrale du jeu en bas) ; texte en HTML aux positions du rendu. Plus simple, aucune dépendance, et l'aperçu
    réutilise le **layout réellement rendu** : l'API (`overview.editor` → `preview`) appelle `choose_layout`,
    donne les positions (`subs_y`, `hook_y`, zone sûre, marges), l'accroche effective (éditeur > rerank > citation
    automatique), le bandeau de test et la conformité au brief (mêmes vérifications que `write_meta`).
  - Sous-titres : découpage en lignes et temps portés en TypeScript à l'identique de `subtitles.py` (group_lines,
    HOLD, LINE_GAP). Police Montserrat ExtraBold servie par l'API (`/media/assets/fonts/…`), taille CSS = taille ASS
    × 0,65 (mesuré : même largeur de texte que libass sur un vrai rendu).
  - **Validé contre un vrai rendu** : aperçu et `clip_1.mp4` comparés à 1,5 s et 6 s (même image, même mot surligné,
    mêmes positions, largeurs de texte à ±1 %) ; puis rendu lancé depuis l'éditeur avec style « box », accroche et
    corrections → `/verify-clip` OK (1080x1920, 30 fps, −14,0 LUFS, synchro 52 ms).
  - Corrections : « Ce mot » (clé = début du mot) ou « Partout (N) » (mot nu, ponctuation de chaque occurrence
    gardée, sur toute la plage). Mots peu sûrs (confiance < 0,5) soulignés et listés.
  - « Variation anti-doublon » et « Recadrage » grisés (M6). Si la facecam n'a pas de sens (caméra plein cadre,
    aucune webcam), l'écran le dit et l'aperçu montre le repli en Flou, comme le rendu.
- **M8 — étape 7 (pipeline, parcours complet), 2026-11-21**
  - `/pipeline` (maquette 6) : colonnes À revoir / Rendu / Posté, puis Payé en pleine largeur ; filtre par campagne ;
    totaux « payé cette semaine » et « en attente » (estimations des clips postés).
  - Carte : miniature (ouvre le clip), titre (ouvre l'éditeur sur ce moment), créateur · durée, verdict du brief et
    pastilles Overlay / #tag / Durée / Mention / Titre (✕ en rose si non respecté).
    - À revoir : ce qui bloque et **où le corriger** (overlay → brief, durée → éditeur…). Campagne de test :
      « ne doit pas être posté » (le cœur refuse de toute façon d'enregistrer un post pour une campagne de test).
    - Rendu : « Copier la légende », puis **URL du post par plateforme du brief** → `POST /api/clips/…/log` → Posté.
    - Posté : vues, estimation (ou « sous le minimum »), rappel de soumettre le lien sur Content Rewards si le brief
      fixe un délai ; saisie des vues et du montant payé par plateforme → Payé.
  - « Démonétisation » (maquette) = safety de M6 : pas affiché tant qu'il n'existe pas.
  - Tests : le parcours posté → payé est testé **avec une API simulée** (Playwright `page.route`) pour ne jamais écrire
    dans posts.csv ; la logique d'écriture et de calcul reste couverte par pytest (log_post, estimate, budget, statuts).
  - Parcours sans terminal (une fois `qclip serve` et `pnpm dev` lancés), validé étape par étape sur la VOD de test :
    brief (étape 3) → nouvelle VOD + analyse en direct (4) → tri au clavier (5) → éditeur + rendu, `/verify-clip` OK (6)
    → pipeline (7). Seul l'enregistrement d'un vrai post n'a pas été fait : il n'existe encore aucune campagne réelle.
- **M7, 2026-11-21** — mesure complète (tout refait, `--force`) sur la VOD de test : 3 h 59, 5 078 messages de chat,
  24 zones, rendu des 8 meilleurs clips. i7-8550U 4 cœurs, sur secteur. **21,1 min de bout en bout, réseau compris
  (≈ 4 min) → ≈ 17 min de calcul. Objectif < 30 min atteint.**

  | Étape | Temps | Détail |
  |---|---|---|
  | Repérage | 2 min 39 | audio 4 h (réseau) 1 min 55, chat 11 s, volume RMS 28 s, fenêtres 0,3 s |
  | Téléchargement des zones | 2 min 09 | ≈ 5 s / zone (réseau), recalage audio compris |
  | Extraction de l'audio | 16 s | ≈ 0,6 s / zone |
  | Transcription (Parakeet) | 9 min 14 | chargement 5 s, 12-30 s / zone (médiane ≈ 23 s) |
  | Détection des moments | 4 min 07 | CLAP 3 min 38 (dont chargement 34 s), coupes 28 s |
  | Rendu de 8 clips + meta | 2 min 45 | 10-19 s d'encodage QSV + 4-6 s de meta par clip |

  - **Coupes de scène cherchées seulement autour des bornes** (±1,5 s, 2 extraits de 3 s par zone) au lieu de toute
    la zone : elles ne servent qu'à caler une borne à moins de 1 s (`snap_to_cuts`). Le passage est choisi sans coupes,
    puis rechoisi avec celles trouvées près de ses bornes (bornes avant calage identiques → même résultat). Extraits
    alignés sur la grille de 0,1 s du fichier : mêmes images échantillonnées, donc mêmes instants de coupe.
    11,2 s → 1,2 s par zone, **≈ 4 min 30 → 28 s** sur la VOD. Vérifié : 24 candidats identiques (numéros, bornes,
    scores, raisons, texte) ; test pytest sur une vidéo générée avec coupes franches.
  - **Transcription laissée telle quelle** (mesuré sur une zone) : onnxruntime prend déjà 4 threads (8 threads :
    +50 % de temps, l'hyperthreading gêne) ; `batch_size` 4 de la VAD : −10 à −17 %, **mais change le texte**
    (remplissage des lots) → qualité et clés des corrections de l'éditeur (début de chaque mot) en jeu : refusé.
  - Résultats de la mesure identiques à avant : 24/24 transcriptions, 24 candidats, fenêtres du repérage. Les 8 rendus :
    1080x1920, 30 i/s, 27,5-38,4 s, AAC, −13,8 à −14,8 LUFS.
  - `work/<id>/timings.json` contient maintenant ces mesures (par étape et par zone) : l'écran VOD s'en sert pour
    estimer le temps restant des prochaines analyses.
  - Pistes restantes si besoin (non faites, l'objectif est atteint) : télécharger la zone suivante pendant qu'on
    transcrit la précédente (≈ 2 min de réseau masquées) ; garder CLAP chargé entre deux VOD (34 s).
- **M6, 2026-11-21**
  - **Layout `crop` (Recadrage)** : bande 9:16 de toute la hauteur de la source (608 px pour du 1080p), agrandie en
    1080x1920, **centrée sur le visage si la caméra occupe l'image** (`fullcam`, détection YuNet existante), sinon au
    centre (une webcam dans un coin n'est pas le sujet). Positions du texte = celles de blur. Actif dans le brief et
    l'éditeur. Testé en rendu réel (zone 2 : bande x = 610, visage centré) et dans l'aperçu.
  - Facecam + choix du layout + zoom dans une seule fonction `render.clip_layout`, utilisée par le rendu **et** par
    l'aperçu de l'éditeur (plus de duplication possible).
  - **Variation anti-doublon = zoom** : image agrandie (1,00-1,10) et recadrée au centre **après** le layout, avant
    l'overlay et les sous-titres (le texte reste net et dans les zones sûres). Défaut `render.zoom: 1.02`
    (config.yaml), réglable par clip dans l'éditeur (`edits.json` → `zoom`). Miniature : même graphe, donc même zoom.
  - **Safety sans LLM vision** (`qclip/safety.py`) : règle YouTube des 7 premières secondes. Signalés : gros mots
    (liste `PROFANITY` de meta.py, sur les mots corrigés) et sons « explosion » / « coups de feu » de CLAP (p ≥ 0,5).
    **« car crash » écarté** : il dépasse 0,5 sur 5 % d'un stream Just Chatting (bruits de bureau), mesuré sur la VOD
    de test → faux positifs. Correctif proposé : le plus petit décalage du début (juste après un évènement) qui dégage
    les 7 s sans passer sous la durée min du brief, sinon « aucun décalage possible ».
    - Après chaque rendu : `clip_<n>.safety.json` + champ `safety` dans `clip_<n>.json`. `qclip safety <campagne>`
      refait les verdicts sans réencoder. Un clip à risque passe « À revoir » dans le pipeline (badge
      « Démonétisation », action « Décaler le début de N s et refaire le rendu »). L'éditeur recalcule le risque sur
      les bornes en cours (bandeau + bouton « Décaler le début »).
    - Images non vérifiées (`use_vision: false`, le 2B testé en M5 était trop faible) : le bandeau le rappelle.
    - VOD de test : 1 clip sur 8 signalé (« enculé » à 2,7 s ; d'autres gros mots jusqu'à 13,3 s → aucun décalage
      possible sans passer sous 15 s).
  - **Lot** : la CLI traitait déjà toutes les sources d'une campagne (`qclip process <campagne>`). Dans l'interface,
    « Plusieurs VOD » sur la page Nouvelle VOD : une URL par ligne (vérifiées, doublons retirés), mises en file dans
    l'ordre, une à la fois.
  - **Bug trouvé et corrigé** : le pipeline lisait tous les `clip_*.json`, y compris le nouveau `clip_3.safety.json`
    → `/api/clips` (pipeline et accueil) plantait. Ne lit plus que `clip_<n>.json` ; test de non-régression.
- **Vision (suite de M6), 2026-11-22**
  - `qclip/vision.py` : 8 images (7 dans les 7 premières secondes + la miniature, 384 px) → Ollama en une requête,
    réponse JSON imposée (violence graphique, gore, images concernées, confiance, description FR) ; modèle déchargé
    après (`keep_alive=0`). `qclip bench-vision <clip>` compare des modèles.
  - Mesuré (VOD de test, Just Chatting, ≈ 2 Go de RAM libre) : 2B **89 s**, 4B **158-241 s** par clip ; les deux
    répondent juste (pas de violence, description correcte). 4B retenu (`llm.vision_model`, descriptions plus précises).
  - **`use_vision: false` par défaut** : activé, il ajouterait ≈ 2,5-4 min par clip rendu (8 clips → l'objectif M7 de
    30 min ne tient plus). À la demande sur les clips à poster : `qclip safety <campagne> --ids 1,3 --vision`.
  - Verdict : images signalées (violence ou gore, confiance ≥ 0,6) → drapeau `image` (lisible par le pipeline,
    l'éditeur et la CLI), pas de décalage automatique (début à régler à l'œil). `safety.vision` = verdict du modèle,
    `{error}` si Ollama ou le modèle manquent (le verdict son + mots reste), `null` si non vérifié.
  - **Bug corrigé** : la miniature n'était jamais lue (`-ss 0` sur une image fixe → ffmpeg n'écrit rien, code 0).
- **Accroches proposées dans l'éditeur, 2026-11-22**
  - Test du 4B pour le texte (16 moments, 46 s chacun) : formulations meilleures que le 2B, mais il **invente** à partir
    des erreurs de transcription (« camp de Daesh », « Big Day »), prête des propos négatifs au créateur et note
    presque tout 4/10 → **pas de rerank automatique** (`use_llm: false`), gabarits par défaut.
  - Bouton « Proposer des accroches (4B) » dans l'éditeur (`POST /api/vods/<id>/moments/<plage>/suggest`, passe par
    la file de tâches) : 3 accroches + un titre, consigne stricte (rien d'inventé, aucun propos négatif prêté),
    filtre de gros mots ; **rien n'est appliqué sans un clic**. ≈ 1 min 30 chargement compris (mesuré : 91 s).
    `llm.text_model` = 4B.
- **Port de l'API : 8766** (au lieu de 8765), 2026-11-22 — un autre programme de la machine (`firetv_link.py`) occupe
  8765 et empêchait `qclip serve` de démarrer. API, client web (`NEXT_PUBLIC_QCLIP_API`), tests e2e, lanceur.
