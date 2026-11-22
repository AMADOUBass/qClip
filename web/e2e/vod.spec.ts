import { expect, test } from "@playwright/test";

// Écran VOD (maquette 3) et ajout d'une VOD, sans rien lancer ni écrire.

const API = process.env.NEXT_PUBLIC_QCLIP_API ?? "http://127.0.0.1:8766";

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
  await page.getByRole("button", { name: "Analyser", exact: true }).click();
  await expect(page.getByText("Colle l'URL d'une VOD Kick, Twitch ou YouTube")).toBeVisible();
  await expect(page).toHaveURL(/\/vod\/new/);
});

test("lot : plusieurs URL → une analyse par VOD, dans l'ordre (API simulée)", async ({ page }) => {
  const posted: string[] = [];
  await page.route(`${API}/api/campaigns/test-fr/vods`, async (route) => {
    posted.push((route.request().postDataJSON() as { url: string }).url);
    await route.fulfill({ status: 202, json: { job: { id: posted.length, status: "queued", video_id: null }, source_rule: "" } });
  });
  await page.goto("/vod/new?campaign=test-fr");
  const box = page.getByLabel("Plusieurs URL, une par ligne");
  await box.fill("https://www.twitch.tv/videos/111\nhttps://example.com/x\nhttps://kick.com/demo/videos/abc");
  await expect(page.getByText(/Pas une VOD Kick, Twitch ou YouTube : https:\/\/example.com\/x/)).toBeVisible();
  await expect(page.getByRole("button", { name: /Analyser les 3 VOD/ })).toBeDisabled();
  await box.fill("https://www.twitch.tv/videos/111\nhttps://kick.com/demo/videos/abc\nhttps://www.twitch.tv/videos/111");
  await page.getByRole("button", { name: "Analyser les 2 VOD" }).click(); // doublon retiré
  await expect(page.getByText("2 analyses en file")).toBeVisible();
  expect(posted).toEqual(["https://www.twitch.tv/videos/111", "https://kick.com/demo/videos/abc"]);
});
