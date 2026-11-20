// Validation du brief côté interface : mêmes règles que le pydantic de qclip/campaign.py (l'API revalide de toute façon).

import { z } from "zod";

const url = z.union([z.literal(""), z.string().regex(/^https?:\/\//, "URL http(s) attendue")]);
const money = z.union([z.nan(), z.number().min(0, "doit être positif")]).optional();
const pct = z.union([z.nan(), z.number().min(0).max(100, "entre 0 et 100")]).optional();

export const briefSchema = z
  .object({
    name: z.string().trim().min(1, "Donne un nom à la campagne"),
    creator: z.string().trim().min(1, "Nom du créateur obligatoire (utilisé dans les titres)"),
    mention: z.union([z.literal(""), z.string().regex(/^@\S+$/, "La mention commence par @, sans espace")]),
    brief_url: url,
    source_platform: z.enum(["kick", "twitch", "youtube"]).nullable(),
    channel: url,
    source_rule: z.string(),
    language: z.enum(["fr", "en"]),
    min_len: z.number({ error: "nombre attendu" }).positive("doit être > 0"),
    max_len: z.number({ error: "nombre attendu" }).positive("doit être > 0"),
    layout: z.enum(["facecam", "blur", "crop"]),
    hashtags: z.array(z.string().regex(/^#\S+$/, "Un hashtag commence par # et n'a pas d'espace")),
    link_in_bio_required: z.boolean(),
    link_in_bio: z.string(),
    dedicated_account: z.boolean(),
    linked_description: z.boolean(),
    country: z.string(),
    min_country_pct: pct,
    min_engagement_pct: pct,
    forbidden: z.array(z.string().min(1)),
    rate_per_1k: z.number({ error: "nombre attendu" }).min(0, "doit être positif"),
    payout_min: money,
    payout_max: money,
    budget_total: money,
    overlay_x: z.number().min(0).max(1),
    overlay_y: z.number().min(0).max(1),
    overlay_width: z.number().gt(0).max(1),
  })
  .refine((v) => v.min_len < v.max_len, { path: ["max_len"], message: "La durée max doit dépasser la durée min" })
  .refine((v) => !v.link_in_bio_required || v.link_in_bio.trim(), {
    path: ["link_in_bio"],
    message: "Quel lien en bio (ex. Risor Tracker) ?",
  });

export type BriefForm = z.infer<typeof briefSchema>;

/** Identifiant de fichier : « FR $4,000 Bichou Miami » → « fr-4000-bichou-miami ». */
export const slugify = (name: string) =>
  name
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64) || "campagne";
