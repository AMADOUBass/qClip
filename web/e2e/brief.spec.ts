import { expect, test } from "@playwright/test";

// Formulaire du brief sans rien enregistrer : validation et placement de l'overlay.

// PNG 4x1 vert, suffisant pour l'aperçu.
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAQAAAABCAYAAAD5PA/NAAAAEUlEQVR4nGNk+M/wn4GBgQEAFQoCAVnbKIQAAAAASUVORK5CYII=",
  "base64",
);

test("erreurs du brief", async ({ page }) => {
  await page.goto("/campaigns/new");
  await page.locator("input[name=min_len]").fill("80");
  await page.getByRole("button", { name: "Enregistrer et ajouter une VOD" }).click();
  await expect(page.getByText("Donne un nom à la campagne")).toBeVisible();
  await expect(page.getByText("La durée max doit dépasser la durée min")).toBeVisible();
  await expect(page.getByText(/Nom du créateur obligatoire/)).toBeVisible();
  await expect(page).toHaveURL(/\/campaigns\/new/);
});

test("hashtag vide ignoré", async ({ page }) => {
  await page.goto("/campaigns/new");
  const input = page.getByPlaceholder("Ajouter un hashtag…");
  await input.fill("bichou");
  await input.press("Enter");
  await input.fill("#");
  await input.blur();
  await expect(page.getByRole("button", { name: "Retirer #bichou" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retirer #", exact: true })).toHaveCount(0);
});

test("glisser l'overlay", async ({ page }) => {
  await page.goto("/campaigns/new");
  await page.locator("input[type=file]").setInputFiles({ name: "overlay.png", mimeType: "image/png", buffer: PNG });
  const overlay = page.getByAltText("Overlay");
  await expect.poll(() => overlay.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth)).toBeTruthy();
  const before = await overlay.getAttribute("style");
  const box = (await overlay.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x - 60, box.y + 150, { steps: 8 });
  await page.mouse.up();
  await expect(overlay).not.toHaveAttribute("style", before!);
});
