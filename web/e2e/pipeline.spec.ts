import { type Page, type Route, expect, test } from "@playwright/test";

// Pipeline (maquette 6) avec une API simulée : rien n'est écrit dans posts.csv. On vérifie ce que l'interface
// envoie (POST …/log) et l'avancement du clip : rendu → posté → payé.

const API = process.env.NEXT_PUBLIC_QCLIP_API ?? "http://127.0.0.1:8766";
const checks = ["overlay", "durée", "mention", "hashtags", "titre ≤ 60"].map((name) => ({ name, ok: true, detail: "ok" }));

function clip(status: string, posts: Record<string, { url: string; views: number; paid: number }> = {}) {
  const views = Object.values(posts).reduce((s, p) => s + p.views, 0);
  const paid = Object.values(posts).reduce((s, p) => s + p.paid, 0);
  return {
    campaign: "demo", campaign_name: "Démo", creator: "Bichou", video_id: "kick-1", clip_id: 3, window: 5,
    title: "Il a rien vu venir", hook: "Il a rien vu venir", duration: 31, status,
    compliance: { ok: true, checks }, caption: "Il a rien vu venir\n\n@bichou #bichou #fyp\n",
    thumbnail: "work/kick-1/clip_3.jpg", video: "work/kick-1/clip_3.mp4", posts, platforms: ["tiktok", "shorts"],
    views, estimate: views / 1000, paid, under_min: false, submit_within_min: 30, rendered_at: "", test_only: false,
  };
}

const revealed: string[] = []; // appels « ouvrir l'Explorateur sur le clip »

async function mockApi(page: Page) {
  const sent: Record<string, unknown>[] = [];
  revealed.length = 0;
  let state = clip("rendu");
  await page.route(`${API}/api/clips**`, async (route: Route) => {
    if (route.request().url().endsWith("/reveal")) {
      revealed.push(new URL(route.request().url()).pathname);
      return route.fulfill({ json: { file: "clip_3.mp4", folder: "output/demo/kick-1" } });
    }
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as { platform: string; url?: string; views?: number; paid?: number };
      sent.push({ path: new URL(route.request().url()).pathname, ...body });
      const posts = { ...state.posts } as Record<string, { url: string; views: number; paid: number }>;
      const p = posts[body.platform] ?? { url: "", views: 0, paid: 0 };
      posts[body.platform] = { url: body.url ?? p.url, views: body.views ?? p.views, paid: body.paid ?? p.paid };
      const paid = Object.values(posts).some((x) => x.paid > 0);
      state = clip(paid ? "paye" : "poste", posts);
      return route.fulfill({ json: { row: {} } });
    }
    return route.fulfill({ json: { items: [state], paid_week: state.paid, pending: state.status === "poste" ? state.estimate : 0 } });
  });
  return sent;
}

test("pipeline : copier, poster, saisir vues et paiement", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const sent = await mockApi(page);
  await page.goto("/pipeline");
  const rendu = page.getByRole("region", { name: "Rendu" });
  await expect(rendu.getByText("Il a rien vu venir")).toBeVisible();

  // Publication en un clic : légende copiée, page d'envoi TikTok ouverte (bloquée ici), Explorateur demandé
  await context.route("https://www.tiktok.com/**", (route) => route.fulfill({ body: "page d'envoi TikTok" }));
  const [upload] = await Promise.all([context.waitForEvent("page"), rendu.getByRole("button", { name: "TikTok" }).click()]);
  expect(upload.url()).toBe("https://www.tiktok.com/tiktokstudio/upload");
  await upload.close();
  await expect(page.getByText("TikTok ouvert")).toBeVisible();
  await expect(page.getByText(/clip_3\.mp4 sélectionné dans l'Explorateur/)).toBeVisible();
  expect(revealed).toEqual(["/api/clips/demo/kick-1/3/reveal"]);
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain("@bichou #bichou");

  // Une URL invalide est refusée sans appel à l'API
  await rendu.getByLabel("URL du post TikTok").fill("pas une url");
  await rendu.getByLabel("URL du post TikTok").press("Enter");
  await expect(page.getByText("Colle l'URL complète du post")).toBeVisible();
  expect(sent).toHaveLength(0);

  await rendu.getByLabel("URL du post TikTok").fill("https://www.tiktok.com/@bichou/video/123");
  await rendu.getByLabel("URL du post TikTok").press("Enter");
  const poste = page.getByRole("region", { name: "Posté" });
  await expect(poste.getByText("Il a rien vu venir")).toBeVisible();
  await expect(poste.getByText(/Soumets le lien sur Content Rewards dans les 30 min/)).toBeVisible();
  expect(sent[0]).toEqual({ path: "/api/clips/demo/kick-1/3/log", platform: "tiktok", url: "https://www.tiktok.com/@bichou/video/123" });

  await poste.getByRole("button", { name: /Vues, paiement/ }).click();
  await poste.getByLabel("Vues TikTok").fill("12800");
  await poste.getByRole("button", { name: "Enregistrer" }).click();
  await expect(poste.getByText("12,8 k")).toBeVisible();
  expect(sent[1]).toMatchObject({ platform: "tiktok", views: 12800 });

  await poste.getByLabel("Payé TikTok").fill("19,20"); // le panneau reste ouvert après l'enregistrement
  await poste.getByRole("button", { name: "Enregistrer" }).click();
  const paye = page.getByRole("region", { name: "Payé" });
  await expect(paye.getByText("19,20 $")).toBeVisible();
  expect(sent[2]).toMatchObject({ platform: "tiktok", paid: 19.2 });
  await expect(page.getByText("Payé cette semaine").locator("..").getByText("19,20 $")).toBeVisible();
});

test("pipeline réel : les clips de test ne sont pas postables", async ({ page, request }) => {
  const data = (await (await request.get(`${API}/api/clips`)).json()) as { items: { test_only: boolean; status: string }[] };
  const tests = data.items.filter((c) => c.test_only);
  test.skip(!tests.length, "aucun clip de campagne de test");
  await page.goto("/pipeline");
  const revoir = page.getByRole("region", { name: "À revoir" });
  await expect(revoir.getByText(/il ne doit pas être posté/).first()).toBeVisible();
  expect(tests.every((c) => c.status === "a_revoir")).toBe(true);
});
