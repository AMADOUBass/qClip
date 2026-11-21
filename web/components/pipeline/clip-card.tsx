"use client";

// Carte d'un clip dans le pipeline (maquette 6). Selon le statut :
// à revoir → ce qui ne va pas et où le corriger ; rendu → copier la légende, coller l'URL du post par plateforme ;
// posté → vues / estimation, saisie des vues et du paiement ; payé → vues et montant payé.

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, ExternalLink, TriangleAlert, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { type ComplianceCheck, type PipelineItem, media, post, put } from "@/lib/api";
import { clock, compact, money } from "@/lib/format";
import { cn } from "@/lib/utils";

type Platform = PipelineItem["platforms"][number];
const PLATFORM_LABEL: Record<Platform, string> = { tiktok: "TikTok", shorts: "Shorts", reels: "Reels" };
const URL_RE = /^https?:\/\/\S+$/;

/** Pastilles de conformité, dans l'ordre de la maquette. */
const CHIPS: { name: string; label: string }[] = [
  { name: "overlay", label: "Overlay" },
  { name: "hashtags", label: "#tag" },
  { name: "durée", label: "Durée" },
  { name: "mention", label: "Mention" },
  { name: "titre ≤ 60", label: "Titre" },
];

function useLog(clip: PipelineItem) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { platform: Platform; url?: string; views?: number; paid?: number }) =>
      post(`/api/clips/${clip.campaign}/${clip.video_id}/${clip.clip_id}/log`, body),
    onSuccess: (_, body) => {
      client.invalidateQueries({ queryKey: ["clips"] });
      client.invalidateQueries({ queryKey: ["dashboard"] });
      toast.success(body.url ? `Post ${PLATFORM_LABEL[body.platform]} enregistré` : body.paid != null ? "Paiement enregistré" : "Vues mises à jour");
    },
    onError: (e) => toast.error(e.message, { duration: 8000 }),
  });
}

export function ClipCard({ clip, wide }: { clip: PipelineItem; wide?: boolean }) {
  const checks = clip.compliance?.checks ?? [];
  const failing = checks.filter((c) => !c.ok);
  const editor = clip.window != null ? `/editor?vod=${clip.video_id}&w=${clip.window}` : null;
  return (
    <article className={cn("rounded-[1.4rem] border bg-surface p-4",
      clip.status === "a_revoir" ? (clip.test_only ? "border-orange/40" : "border-pink/40") : "border-transparent")}>
      <div className="flex gap-4">
        <a href={media(clip.video)} target="_blank" rel="noreferrer" title="Ouvrir le clip"
           className="relative h-40 w-[5.6rem] shrink-0 overflow-hidden rounded-xl bg-ink">
          {/* eslint-disable-next-line @next/next/no-img-element -- miniature locale servie par l'API */}
          <img src={media(clip.thumbnail)} alt="" loading="lazy" className="size-full object-cover" />
        </a>
        <div className="min-w-0 flex-1">
          {editor ? (
            <Link href={editor} className="line-clamp-2 text-[1.05rem] font-semibold hover:underline">{clip.title || clip.hook}</Link>
          ) : <p className="line-clamp-2 text-[1.05rem] font-semibold">{clip.title || clip.hook}</p>}
          <p className="mt-1 font-mono text-sm text-muted-foreground">{clip.creator} · {clip.duration ? clock(clip.duration) : "—"}</p>
          <p className="mt-3 flex flex-wrap gap-2">
            {clip.safety && !clip.safety.ok && (
              <span className="inline-flex items-center gap-1 rounded-lg bg-orange-soft px-2.5 py-1 text-orange"><TriangleAlert className="size-4" /> Démonétisation</span>
            )}
            {clip.compliance?.ok ? (
              <span className="inline-flex items-center gap-1 rounded-lg bg-blue-soft px-2.5 py-1 text-blue"><Check className="size-4" /> OK</span>
            ) : clip.test_only ? (
              <span className="inline-flex items-center gap-1 rounded-lg bg-orange-soft px-2.5 py-1 text-orange">Campagne de test</span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-lg bg-pink-soft px-2.5 py-1 text-pink"><X className="size-4" /> Non conforme</span>
            )}
          </p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {CHIPS.map(({ name, label }) => {
              const c = checks.find((x) => x.name === name);
              if (!c) return null;
              return (
                <span key={name} title={c.detail}
                      className={cn("rounded-md px-2 py-0.5 font-mono text-xs", c.ok ? "bg-blue-soft text-blue" : "bg-pink-soft text-pink")}>
                  {c.ok ? "✓" : "✕"} {label}
                </span>
              );
            })}
          </div>
        </div>
      </div>

      {clip.status === "a_revoir" && <Problems clip={clip} failing={failing} editor={editor} />}
      {clip.status === "rendu" && <Publish clip={clip} />}
      {(clip.status === "poste" || clip.status === "paye") && <Results clip={clip} wide={wide} />}
    </article>
  );
}

/** Ce qui empêche de poster, avec l'endroit où le corriger. */
function Problems({ clip, failing, editor }: { clip: PipelineItem; failing: ComplianceCheck[]; editor: string | null }) {
  const brief = `/campaigns/${clip.campaign}`;
  const fix: Record<string, { text: string; href: string | null; action: string }> = {
    "campagne réelle": { text: "Campagne de test : ce clip sert à vérifier qClip, il ne doit pas être posté.", href: null, action: "" },
    overlay: { text: "Overlay absent — obligatoire dans le brief.", href: brief, action: "Ajouter l'overlay et relancer" },
    durée: { text: "Durée hors des limites du brief.", href: editor, action: "Ajuster dans l'éditeur" },
    mention: { text: "Mention obligatoire absente de la légende.", href: brief, action: "Corriger le brief" },
    hashtags: { text: "Hashtags obligatoires absents de la légende.", href: brief, action: "Corriger le brief" },
    "titre ≤ 60": { text: "Titre trop long (60 caractères max).", href: editor, action: "Revoir dans l'éditeur" },
  };
  return (
    <div className={cn("mt-4 space-y-3 rounded-2xl p-4", clip.test_only ? "bg-orange-soft" : "bg-pink-soft")}>
      {clip.safety && !clip.safety.ok && <SafetyFix clip={clip} />}
      {failing.map((c) => {
        const f = fix[c.name] ?? { text: `${c.name} : ${c.detail}`, href: null, action: "" };
        return (
          <div key={c.name}>
            <p>{f.text}{c.name === "durée" && ` (${c.detail})`}</p>
            {f.href && f.action && (
              <Link href={f.href} className={cn("mt-1 inline-block font-semibold", clip.test_only ? "text-orange" : "text-pink")}>{f.action} →</Link>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Démonétisation : ce qui est dit / entendu dans les 7 premières secondes, et « décaler le début » (+ nouveau rendu). */
function SafetyFix({ clip }: { clip: PipelineItem }) {
  const client = useQueryClient();
  const s = clip.safety as NonNullable<PipelineItem["safety"]>;
  const fix = useMutation({
    mutationFn: async (shift: number) => {
      await put(`/api/vods/${clip.video_id}/moments/${clip.window}`, { start: (clip.vod_start as number) + shift });
      return post(`/api/vods/${clip.video_id}/render`, { windows: [clip.window] });
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["clips"] });
      toast.success("Début décalé, nouveau rendu lancé", { description: "Le clip revient ici une fois rendu." });
    },
    onError: (e) => toast.error(e.message),
  });
  const first = s.flags[0];
  return (
    <div>
      <p>
        {first.kind === "gros mot" ? `Gros mot « ${first.detail} »` : `Son violent (${first.detail})`} à {clock(first.at)}
        {s.flags.length > 1 && ` (+ ${s.flags.length - 1})`} — dans les 7 premières secondes, YouTube limite la pub.
      </p>
      {s.shift_s != null && clip.window != null && clip.vod_start != null ? (
        <button type="button" disabled={fix.isPending} onClick={() => fix.mutate(s.shift_s as number)}
                className="mt-1 font-semibold text-orange disabled:opacity-60">
          Décaler le début de {s.shift_s.toLocaleString("fr-FR")} s et refaire le rendu →
        </button>
      ) : (
        <p className="mt-1 text-sm text-muted-foreground">Aucun décalage possible sans passer sous la durée min : choisir un autre moment.</p>
      )}
    </div>
  );
}

/** Rendu, pas encore posté : copier la légende, puis coller l'URL du post pour chaque plateforme. */
function Publish({ clip }: { clip: PipelineItem }) {
  const copy = () =>
    navigator.clipboard.writeText(clip.caption).then(
      () => toast.success("Légende copiée", { description: clip.caption.split("\n").find(Boolean) }),
      () => toast.error("Copie impossible (permission du navigateur)"),
    );
  return (
    <div className="mt-4 space-y-2">
      <button type="button" onClick={copy} className="flex h-12 w-full items-center justify-center gap-2 rounded-2xl bg-yellow font-semibold">
        <Copy className="size-4" /> Copier la légende
      </button>
      {clip.platforms.map((p) => <UrlField key={p} clip={clip} platform={p} />)}
    </div>
  );
}

function UrlField({ clip, platform }: { clip: PipelineItem; platform: Platform }) {
  const [url, setUrl] = useState("");
  const log = useLog(clip);
  // Entrée puis perte du focus appellent tous deux submit : le champ est vidé à l'envoi pour ne poster qu'une fois.
  const submit = () => {
    const value = url.trim();
    if (!value || log.isPending) return;
    if (!URL_RE.test(value)) return toast.error("Colle l'URL complète du post (https://…)");
    setUrl("");
    log.mutate({ platform, url: value }, { onError: () => setUrl(value) });
  };
  return (
    <label className="flex h-12 items-center gap-3 rounded-2xl border border-line bg-secondary/60 px-4">
      <span className="w-14 font-mono text-xs uppercase text-muted-foreground">{platform}</span>
      <input value={url} onChange={(e) => setUrl(e.target.value)} disabled={log.isPending}
             onKeyDown={(e) => e.key === "Enter" && submit()} onBlur={submit}
             placeholder="Colle l'URL du post" aria-label={`URL du post ${PLATFORM_LABEL[platform]}`}
             className="min-w-0 flex-1 bg-transparent outline-none" />
    </label>
  );
}

/** Posté / payé : vues et gains ; saisie des vues et du paiement par plateforme. */
function Results({ clip, wide }: { clip: PipelineItem; wide?: boolean }) {
  const [open, setOpen] = useState(false);
  const posted = (Object.entries(clip.posts) as [Platform, NonNullable<PipelineItem["posts"][Platform]>][]).filter(([, p]) => p.url);
  const missing = clip.platforms.filter((p) => !clip.posts[p]?.url);
  return (
    <div className="mt-4 border-t border-line pt-4">
      <div className="flex items-end justify-between">
        <div>
          <p className="text-sm text-muted-foreground">Vues</p>
          <p className="font-mono text-xl">{clip.views ? compact(clip.views) : "—"}</p>
        </div>
        <div className="text-right">
          {clip.status === "paye" ? (
            <><p className="text-sm text-muted-foreground">Payé</p><p className="font-display text-2xl font-bold text-olive">{money(clip.paid)}</p></>
          ) : clip.under_min ? (
            <><p className="text-sm text-muted-foreground">Sous le minimum</p><p className="font-display text-2xl font-bold text-muted-foreground">—</p></>
          ) : (
            <><p className="text-sm text-muted-foreground">Estimé</p><p className="font-display text-2xl font-bold">{money(clip.estimate)}</p></>
          )}
        </div>
      </div>
      {clip.status === "poste" && clip.submit_within_min != null && (
        <p className="mt-3 rounded-xl bg-orange-soft px-3 py-2 text-sm text-orange">
          Soumets le lien sur Content Rewards dans les {clip.submit_within_min} min qui suivent le post
        </p>
      )}
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
              className="mt-3 text-sm font-medium text-blue">{open ? "Fermer" : "Vues, paiement, autres plateformes"}</button>
      {open && (
        <div className={cn("mt-3 grid gap-2", wide && "md:grid-cols-2")}>
          {posted.map(([platform, p]) => <PostRow key={platform} clip={clip} platform={platform} views={p.views} paid={p.paid} url={p.url} />)}
          {missing.map((p) => <UrlField key={p} clip={clip} platform={p} />)}
        </div>
      )}
    </div>
  );
}

function PostRow({ clip, platform, views, paid, url }: { clip: PipelineItem; platform: Platform; views: number; paid: number; url: string }) {
  const [v, setV] = useState(views ? String(views) : "");
  const [amount, setAmount] = useState(paid ? String(paid) : "");
  const log = useLog(clip);
  const save = () => {
    const nv = v.trim() ? Number(v.replace(/\s/g, "")) : undefined;
    const np = amount.trim() ? Number(amount.replace(",", ".")) : undefined;
    if ((nv != null && (!Number.isInteger(nv) || nv < 0)) || (np != null && (Number.isNaN(np) || np < 0)))
      return toast.error("Vues : nombre entier ; payé : montant en $ (ex. 7,20)");
    if (nv === views && (np ?? 0) === paid) return;
    log.mutate({ platform, views: nv, paid: np !== paid ? np : undefined });
  };
  return (
    <div className="flex items-center gap-2 rounded-2xl border border-line bg-secondary/60 p-2 pl-4">
      <a href={url} target="_blank" rel="noreferrer" className="flex w-20 items-center gap-1 font-mono text-xs uppercase text-blue">
        {platform} <ExternalLink className="size-3" />
      </a>
      <input value={v} onChange={(e) => setV(e.target.value)} inputMode="numeric" placeholder="Vues" aria-label={`Vues ${PLATFORM_LABEL[platform]}`}
             className="h-9 w-24 min-w-0 rounded-lg border border-line bg-surface px-2 font-mono text-sm outline-none focus:border-blue" />
      <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" placeholder="Payé $" aria-label={`Payé ${PLATFORM_LABEL[platform]}`}
             className="h-9 w-24 min-w-0 rounded-lg border border-line bg-surface px-2 font-mono text-sm outline-none focus:border-blue" />
      <button type="button" onClick={save} disabled={log.isPending} className="h-9 rounded-lg bg-ink px-3 text-sm font-medium text-yellow disabled:opacity-60">
        Enregistrer
      </button>
    </div>
  );
}
