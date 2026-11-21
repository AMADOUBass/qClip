import { expect, test } from "@playwright/test";

// Éditeur (maquette 5) sans rien enregistrer : transcription, aperçu, réglages, ligne de temps.

const API = process.env.NEXT_PUBLIC_QCLIP_API ?? "http://127.0.0.1:8765";

test("éditeur : aperçu et ligne de temps", async ({ page, request }) => {
  const vods = (await (await request.get(`${API}/api/vods`)).json()) as { video_id: string }[];
  test.skip(!vods.length, "aucune VOD repérée sur cette machine");
  const res = await request.get(`${API}/api/vods/${vods[0].video_id}/moments`);
  test.skip(!res.ok(), "analyse pas terminée");
  const { moments } = (await res.json()) as { moments: { window: number }[] };
  const editor = await (await request.get(`${API}/api/vods/${vods[0].video_id}/moments/${moments[0].window}/editor`)).json();

  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`/editor?vod=${vods[0].video_id}&w=${moments[0].window}`);
  await expect(page.getByText("Transcription")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator("canvas")).toBeVisible();
  await expect(page.getByRole("button", { name: /Néon jaune/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Recadrage" })).toBeDisabled(); // M6
  await expect(page.getByLabel("Accroche")).toHaveValue(editor.hook);

  // Clic au milieu de la ligne de temps : un mot de la transcription devient le mot courant
  const timeline = page.getByRole("group", { name: "Ligne de temps du clip" });
  await timeline.scrollIntoViewIfNeeded();
  const box = (await timeline.boundingBox())!;
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await expect(page.locator("section").first().locator("button.bg-yellow")).toHaveCount(1);

  // Zones TikTok / Shorts
  await page.getByRole("button", { name: /Zones TikTok/ }).click();
  await expect(page.getByText("PSEUDO · LÉGENDE · MUSIQUE")).toBeVisible();
  expect(errors).toEqual([]);
});
