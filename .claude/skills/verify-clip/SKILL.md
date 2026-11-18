---
name: verify-clip
description: Vérifie visuellement un clip rendu par qClip (format, durée, sous-titres, zones sûres, audio). À utiliser après chaque rendu, avant de déclarer une étape de rendu terminée.
---

Pour chaque clip à vérifier (`output/<id>/clip_<n>.mp4`) :

1. `ffprobe` : vérifier 1080x1920, fps attendu, durée entre min_len et max_len, une piste audio AAC.
2. Extraire 4 images dans `work/<id>/verify/` : à 0,5 s, à 2 s, au milieu, et 1 s avant la fin
   (`ffmpeg -ss <t> -i clip.mp4 -frames:v 1 work/<id>/verify/clip_<n>_<t>.png`).
3. Regarder chaque image avec Read et contrôler :
   - les sous-titres sont lisibles, pas coupés, hors des 20 % du bas et du bord droit ;
   - l'accroche est visible sur l'image à 0,5 s ;
   - le gameplay n'est ni étiré ni flou (layout blur : fond flou, image nette au centre).
4. Synchronisation : comparer le mot surligné sur l'image du milieu avec `transcript.json` à ce timestamp (écart ≤ 100 ms).
5. Audio : `ffmpeg -i clip.mp4 -af ebur128 -f null -` → intégré proche de −14 LUFS (±1).
6. Si `clip_<n>.safety.json` existe, rappeler son verdict.

Rendre un court rapport : OK / problèmes trouvés, avec le chemin de l'image concernée. Ne jamais déclarer le rendu bon sans avoir regardé les images.
