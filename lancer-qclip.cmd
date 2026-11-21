@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title qClip
rem Lance qClip sans terminal : double-clic sur ce fichier.
rem API (http://127.0.0.1:8765) et interface (http://localhost:3000) dans deux fenêtres réduites,
rem puis ouverture du navigateur. Pour tout arrêter : fermer les fenêtres « qClip API » et « qClip interface ».

cd /d "%~dp0"

for %%T in (uv pnpm ffmpeg) do (
  where %%T >nul 2>nul || (
    echo [qClip] « %%T » est introuvable dans le PATH : installe-le puis relance ce fichier.
    if "%%T"=="uv" echo         winget install --id astral-sh.uv -e
    if "%%T"=="pnpm" echo         npm install -g pnpm
    if "%%T"=="ffmpeg" echo         winget install --id Gyan.FFmpeg -e
    pause
    exit /b 1
  )
)

if not exist "web\node_modules" (
  echo [qClip] Première fois : installation des dépendances de l'interface…
  pushd web
  call pnpm install || (popd & echo [qClip] pnpm install a échoué. & pause & exit /b 1)
  popd
)

netstat -ano | findstr /r /c:"127.0.0.1:8765 .*LISTENING" >nul
if errorlevel 1 (
  echo [qClip] Démarrage de l'API…
  start "qClip API" /min cmd /k "uv run qclip serve"
) else (
  echo [qClip] API déjà lancée.
)

netstat -ano | findstr /r /c:":3000 .*LISTENING" >nul
if errorlevel 1 (
  echo [qClip] Démarrage de l'interface…
  start "qClip interface" /min cmd /k "cd /d web && pnpm dev"
) else (
  echo [qClip] Interface déjà lancée.
)

echo [qClip] En attente de l'interface (la première compilation prend jusqu'à 2 minutes, ensuite quelques secondes)…
set /a tries=0
:wait
curl -s -o nul http://localhost:3000 && goto ready
set /a tries+=1
if !tries! geq 90 goto slow
timeout /t 2 /nobreak >nul
goto wait

:ready
start "" http://localhost:3000
echo [qClip] Prêt : http://localhost:3000 — cette fenêtre se ferme toute seule.
timeout /t 4 /nobreak >nul
exit /b 0

:slow
echo [qClip] L'interface ne répond pas après 3 minutes. Regarde la fenêtre « qClip interface » pour l'erreur.
pause
exit /b 1
