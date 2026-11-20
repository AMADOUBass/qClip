import { expect, test } from "@playwright/test";

// Écran VOD (maquette 3) et ajout d'une VOD, sans rien lancer ni écrire.

const API = process.env.NEXT_PUBLIC_QCLIP_API ?? "http://127.0.0.1:8765";

test("écran d'une VOD repérée", async ({ page, request }) => {
  const vods = (await (await request.get(`${API}/api/vods`)).json()) as { video_id: string }[];
  test.skip(!vods.length, "aucune VOD repérée sur cette machine");
  const vod = (await (await request.get(`${API}/api/vods/${vods[0].video_id}`)).json()) as { windows: unknown[] };
  await page.goto(`/vod/${vods[0].video_id}`);
  await expect(page.getByText("Radar du hype")).toBeVisible();
  await expect(page.getByText(`${vod.windows.length} zones repérées`)).toBeVisible();
  await expect(page.getByText("1 · Repérage")).toBeVisible();
  await expect(page.getByText("2 · Traitement des zones")).toBeVisible();
  await expect(page.getByText(/^#\d{2}$/)).toHaveCount(vod.windows.length);
});

test("VOD inconnue", async ({ page }) => {
  await page.goto("/vod/twitch-0");
  await expect(page.getByRole("heading", { name: "VOD introuvable" })).toBeVisible();
});

test("nouvelle VOD : URL refusée tant qu'elle n'est pas une VOD Kick, Twitch ou YouTube", async ({ page }) => {
  await page.goto("/vod/new");
  await page.getByLabel("URL de la VOD").fill("https://example.com/video");
  await page.getByRole("button", { name: "Analyser" }).click();
  await expect(page.getByText("Colle l'URL d'une VOD Kick, Twitch ou YouTube")).toBeVisible();
  await expect(page).toHaveURL(/\/vod\/new/);
});
