import { expect, test } from "@playwright/test";

// Fumée : chaque écran s'affiche avec la barre latérale, sans erreur dans la console ; la palette Ctrl K s'ouvre.

const ROUTES = [
  ["/", "Accueil"],
  ["/campaigns", "Campagnes"],
  ["/vod", "VOD"],
  ["/sort", "Tri"],
  ["/editor", "Éditeur"],
  ["/pipeline", "Pipeline"],
] as const;

for (const [path, label] of ROUTES) {
  test(`écran ${label}`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    await page.goto(path);
    await expect(page.getByRole("link", { name: label, exact: true })).toBeVisible();
    await expect(page.locator("h1")).toHaveText(/\S/); // titre affiché (après hydratation pour l'accueil)
    await page.screenshot({ path: `e2e/__screens__/${label}.png`, fullPage: true });
    expect(errors).toEqual([]);
  });
}

test("palette Ctrl K", async ({ page }) => {
  await page.goto("/");
  await page.locator("h1").waitFor();
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Nouvelle VOD")).toBeVisible();
  await expect(dialog.getByText("Trier les moments")).toBeVisible();
  await page.screenshot({ path: "e2e/__screens__/Palette.png" });
  await page.keyboard.type("trier");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/sort$/);
});
