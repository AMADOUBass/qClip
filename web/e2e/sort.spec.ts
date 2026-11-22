import { expect, test } from "@playwright/test";

// Tri (maquette 4) sans rien décider : affichage, navigation J / K, libellés des raisons.

const API = process.env.NEXT_PUBLIC_QCLIP_API ?? "http://127.0.0.1:8766";

test("tri : affichage et navigation au clavier", async ({ page, request }) => {
  const vods = (await (await request.get(`${API}/api/vods`)).json()) as { video_id: string }[];
  test.skip(!vods.length, "aucune VOD repérée sur cette machine");
  const res = await request.get(`${API}/api/vods/${vods[0].video_id}/moments`);
  test.skip(!res.ok(), "analyse pas terminée");
  const data = (await res.json()) as { moments: { window: number }[] };
  test.skip(data.moments.length < 2, "pas assez de moments");

  await page.goto(`/sort?vod=${vods[0].video_id}&w=${data.moments[0].window}`);
  await expect(page.getByRole("heading", { name: `Moment 1 / ${data.moments.length}` })).toBeVisible();
  await expect(page.getByText("Progression")).toBeVisible();
  await expect(page.getByRole("slider", { name: "Début du clip" })).toBeVisible();
  await page.keyboard.press("k");
  await expect(page.getByRole("heading", { name: `Moment 2 / ${data.moments.length}` })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`w=${data.moments[1].window}`));
  await page.keyboard.press("j");
  await expect(page.getByRole("heading", { name: `Moment 1 / ${data.moments.length}` })).toBeVisible();
});

test("tri sans VOD connue", async ({ page }) => {
  await page.goto("/sort?vod=twitch-0");
  await expect(page.getByRole("heading", { name: "Moments pas encore prêts" })).toBeVisible();
});
