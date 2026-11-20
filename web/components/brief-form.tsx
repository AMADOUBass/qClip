"use client";

// Brief de campagne (maquette 2) : création et modification.

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Link2, Upload, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { type UseFormRegisterReturn, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import { type Brief, type BriefView, api, media, post, put } from "@/lib/api";
import { type BriefForm as Form, briefSchema, slugify } from "@/lib/brief-schema";
import { cn } from "@/lib/utils";

const COUNTRIES = ["France", "Belgique", "Suisse", "Canada", "Maroc", "Algérie", "Tunisie", "Sénégal", "Côte d'Ivoire", "États-Unis", "Royaume-Uni"];

const DEFAULT_BRIEF: Brief = {
  name: "", creator: "", platforms: ["tiktok", "shorts", "reels"], rate_per_1k: 1, sources: [],
  clip: { min_len: 15, max_len: 59 }, required: { mention: "", hashtags: [], caption_note: "" }, forbidden: [],
  layout: "facecam", language: "fr", test_only: false, facecam: null, brief_url: "", source_platform: null, channel: "",
  source_rule: "", budget_total: null, payout_min: null, payout_max: null, overlay: null,
  requirements: { link_in_bio: "", dedicated_account: false, linked_description: false, submit_within_min: null },
  audience: { country: "", min_country_pct: null, min_engagement_pct: null },
};

const num = (v: number | null | undefined) => (v == null ? Number.NaN : v);
const opt = (v: number | undefined) => (v == null || Number.isNaN(v) ? null : v);

function toForm(b: Brief): Form {
  return {
    name: b.name, creator: b.creator, mention: b.required.mention, brief_url: b.brief_url,
    source_platform: b.source_platform, channel: b.channel, source_rule: b.source_rule,
    language: b.language === "en" ? "en" : "fr", min_len: b.clip.min_len, max_len: b.clip.max_len, layout: b.layout,
    hashtags: b.required.hashtags, link_in_bio_required: !!b.requirements.link_in_bio,
    link_in_bio: b.requirements.link_in_bio, dedicated_account: b.requirements.dedicated_account,
    linked_description: b.requirements.linked_description, country: b.audience.country,
    min_country_pct: num(b.audience.min_country_pct), min_engagement_pct: num(b.audience.min_engagement_pct),
    forbidden: b.forbidden, rate_per_1k: b.rate_per_1k, payout_min: num(b.payout_min), payout_max: num(b.payout_max),
    budget_total: num(b.budget_total), overlay_x: b.overlay?.x ?? 0.72, overlay_y: b.overlay?.y ?? 0.3,
    overlay_width: b.overlay?.width ?? 0.18,
  };
}

function toBrief(f: Form, base: Brief, overlayFile: string | null): Brief {
  return {
    ...base,
    name: f.name.trim(), creator: f.creator.trim(), rate_per_1k: f.rate_per_1k,
    clip: { min_len: f.min_len, max_len: f.max_len }, layout: f.layout, language: f.language,
    required: { ...base.required, mention: f.mention, hashtags: f.hashtags }, forbidden: f.forbidden,
    brief_url: f.brief_url, source_platform: f.source_platform, channel: f.channel, source_rule: f.source_rule.trim(),
    budget_total: opt(f.budget_total), payout_min: opt(f.payout_min), payout_max: opt(f.payout_max),
    overlay: overlayFile ? { file: overlayFile, x: f.overlay_x, y: f.overlay_y, width: f.overlay_width } : null,
    requirements: { ...base.requirements, link_in_bio: f.link_in_bio_required ? f.link_in_bio.trim() : "",
      dedicated_account: f.dedicated_account, linked_description: f.linked_description },
    audience: { country: f.country, min_country_pct: opt(f.min_country_pct), min_engagement_pct: opt(f.min_engagement_pct) },
  };
}

/** Checklist « avant de poster », recalculée pendant la saisie (le serveur fait la même à l'enregistrement). */
function checklist(f: Form, hasOverlay: boolean) {
  const items: { label: string; detail: string }[] = [];
  const who = f.creator || "le créateur";
  if (f.dedicated_account) items.push({ label: `Compte dédié à ${who}`, detail: f.link_in_bio_required && f.link_in_bio ? `Avec le lien ${f.link_in_bio} en bio` : "" });
  else if (f.link_in_bio_required && f.link_in_bio) items.push({ label: `Lien ${f.link_in_bio} en bio`, detail: "" });
  if (f.source_rule) items.push({ label: `Source : ${f.source_rule}`, detail: "Vérifié sur chaque VOD ajoutée" });
  if (hasOverlay) items.push({ label: `Overlay ${f.source_platform?.toUpperCase() ?? ""} visible`.replace("  ", " "), detail: "Incrusté automatiquement au rendu" });
  for (const tag of f.hashtags) items.push({ label: `${tag} dans la description`, detail: "Ajouté à la légende générée" });
  if (f.mention) items.push({ label: `Mention ${f.mention}`, detail: "Ajoutée à la légende générée" });
  for (const rule of f.forbidden) items.push({ label: `Rien qui : ${rule.toLowerCase()}`, detail: "À vérifier par toi avant de poster" });
  if (f.linked_description) items.push({ label: "Description liée au clip", detail: "Légende générée à partir du clip" });
  return items;
}

export function BriefFormView({ initial, slug }: { initial?: BriefView; slug?: string }) {
  const router = useRouter();
  const client = useQueryClient();
  const base = initial?.brief ?? DEFAULT_BRIEF;
  const [overlayFile, setOverlayFile] = useState<string | null>(base.overlay?.file ?? null);
  const [overlayUpload, setOverlayUpload] = useState<File | null>(null);
  const [overlayPreview, setOverlayPreview] = useState<string | null>(base.overlay?.url ? media(base.overlay.url) : null);
  const { register, handleSubmit, setValue, control, formState: { errors } } = useForm({
    resolver: zodResolver(briefSchema),
    defaultValues: toForm(base),
  });
  const values = useWatch({ control }) as Form;

  const save = useMutation({
    mutationFn: async ({ form, next }: { form: Form; next: "vod" | "stay" }) => {
      const target = slug ?? slugify(form.name);
      let file = overlayFile;
      if (!slug) await post<BriefView>("/api/campaigns", { slug: target, brief: toBrief(form, base, null) });
      if (overlayUpload) {
        const data = new FormData();
        data.append("file", overlayUpload);
        const uploaded = await api<BriefView>(`/api/campaigns/${target}/overlay`, { method: "POST", body: data });
        file = uploaded.brief.overlay?.file ?? null;
      }
      const saved = await put<BriefView>(`/api/campaigns/${target}`, { brief: toBrief(form, base, file) });
      return { saved, next };
    },
    onSuccess: ({ saved, next }) => {
      client.invalidateQueries();
      toast.success(`Brief enregistré · ${saved.brief.name}`);
      router.push(next === "vod" ? `/vod/new?campaign=${saved.slug}` : `/campaigns/${saved.slug}`);
    },
    onError: (e) => toast.error(e.message, { duration: 8000 }),
  });

  const submit = (next: "vod" | "stay") => handleSubmit((form) => save.mutate({ form, next }),
    () => toast.error("Le brief contient des erreurs : elles sont signalées en rouge"));

  return (
    <form onSubmit={(e) => e.preventDefault()}>
      <header className="mb-8 flex flex-wrap items-end justify-between gap-6">
        <div className="min-w-0 flex-1">
          <p className="eyebrow mb-3">Campagnes / {slug ? "brief" : "nouveau brief"}</p>
          <input {...register("name")} placeholder="Nom de la campagne" aria-label="Nom de la campagne"
                 className="title-xl w-full bg-transparent outline-none placeholder:text-muted-foreground/50" />
          <Err msg={errors.name?.message} />
          {!slug && values.name && <p className="mt-1 font-mono text-xs text-muted-foreground">campaigns/{slugify(values.name)}.yaml</p>}
        </div>
        <div className="flex gap-3">
          <button type="button" onClick={() => router.back()} className="h-12 rounded-2xl border border-line bg-surface px-6 font-medium">Annuler</button>
          {slug && <button type="button" disabled={save.isPending} onClick={submit("stay")} className="h-12 rounded-2xl border border-line bg-surface px-6 font-medium">Enregistrer</button>}
          <button type="button" disabled={save.isPending} onClick={submit("vod")} className="h-12 rounded-2xl bg-yellow px-6 font-semibold disabled:opacity-60">
            {save.isPending ? "Enregistrement…" : "Enregistrer et ajouter une VOD"}
          </button>
        </div>
      </header>

      <div className="grid grid-cols-[minmax(0,1.85fr)_minmax(0,1fr)] gap-8">
        <div className="flex flex-col gap-8">
          <Section title="Sources">
            <Field label="Lien du brief" error={errors.brief_url?.message}>
              <div className="relative">
                <Link2 className="absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted-foreground" />
                <input {...register("brief_url")} placeholder="https://docs.google.com/document/d/…" className={cn(INPUT, "pl-11")} />
              </div>
            </Field>
            <div className="grid grid-cols-2 gap-5">
              <Field label="Plateforme source" group>
                <Segmented value={values.source_platform ?? ""} onChange={(v) => setValue("source_platform", v as Form["source_platform"])}
                           options={[["kick", "KICK"], ["twitch", "TWITCH"], ["youtube", "YOUTUBE"]]} mono />
              </Field>
              <Field label="Chaîne" error={errors.channel?.message}>
                <input {...register("channel")} placeholder="https://kick.com/…" className={INPUT} />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-5">
              <Field label="Créateur (nom affiché dans les titres)" error={errors.creator?.message}>
                <input {...register("creator")} placeholder="Bichou" className={INPUT} />
              </Field>
              <Field label="Mention obligatoire" error={errors.mention?.message}>
                <input {...register("mention")} placeholder="@bichouu" className={INPUT} />
              </Field>
            </div>
            <Field label="Règle de source" hint="qClip te le rappellera sur chaque VOD que tu ajoutes.">
              <input {...register("source_rule")} placeholder="Uniquement le contenu des streams de … " className={cn(INPUT, "border-yellow/70 bg-yellow-soft/40")} />
            </Field>
          </Section>

          <Section title="Format">
            <div className="grid grid-cols-[1.5fr_1fr_1fr] gap-5">
              <Field label="Langue" group>
                <Segmented value={values.language} onChange={(v) => setValue("language", v as Form["language"])}
                           options={[["fr", "Français"], ["en", "Anglais"]]} />
              </Field>
              <Field label="Durée min" error={errors.min_len?.message}><Suffix unit="s" reg={register("min_len", { valueAsNumber: true })} /></Field>
              <Field label="Durée max" error={errors.max_len?.message}><Suffix unit="s" reg={register("max_len", { valueAsNumber: true })} /></Field>
            </div>
            <Field label="Layout par défaut" group>
              <div className="grid grid-cols-3 gap-4">
                <LayoutCard selected={values.layout === "facecam"} onClick={() => setValue("layout", "facecam")} title="Facecam" detail="Webcam en haut, jeu en bas" split />
                <LayoutCard selected={values.layout === "blur"} onClick={() => setValue("layout", "blur")} title="Flou" detail="Image nette sur fond flouté" />
                <LayoutCard selected={false} disabled title="Recadrage" detail="Disponible en M6" />
              </div>
            </Field>
          </Section>

          <Section title="Obligations">
            <Field label="Hashtags obligatoires" group error={errors.hashtags?.message ?? (Array.isArray(errors.hashtags) ? errors.hashtags.find(Boolean)?.message : undefined)}>
              <Chips values={values.hashtags ?? []} onChange={(v) => setValue("hashtags", v, { shouldValidate: true })}
                     placeholder="Ajouter un hashtag…" normalize={(t) => (t.startsWith("#") ? t : `#${t}`).replace(/\s+/g, "")} tone="olive" />
            </Field>
            <div className="grid grid-cols-2 gap-5">
              <OverlayDrop file={overlayUpload?.name ?? overlayFile} onFile={(f) => {
                setOverlayUpload(f);
                setOverlayFile(overlayFile ?? f.name);
                setOverlayPreview(URL.createObjectURL(f));
              }} onClear={() => { setOverlayUpload(null); setOverlayFile(null); setOverlayPreview(null); }} />
              <div className="flex flex-col gap-3">
                <Toggle checked={values.link_in_bio_required} onChange={(v) => setValue("link_in_bio_required", v)}
                        label={`Lien en bio requis${values.link_in_bio ? ` (${values.link_in_bio})` : ""}`} />
                {values.link_in_bio_required && (
                  <div>
                    <input {...register("link_in_bio")} placeholder="Nom du lien (ex. Risor Tracker)" className={INPUT} />
                    <Err msg={errors.link_in_bio?.message} />
                  </div>
                )}
                <Toggle checked={values.dedicated_account} onChange={(v) => setValue("dedicated_account", v)} label="Compte dédié requis" />
                <Toggle checked={values.linked_description} onChange={(v) => setValue("linked_description", v)} label="Description liée au clip" />
              </div>
            </div>
          </Section>

          <Section title="Audience et interdits">
            <div className="grid grid-cols-[1.5fr_0.6fr_1fr] gap-5">
              <Field label="Vues minimum par pays">
                <select {...register("country")} className={INPUT}>
                  <option value="">—</option>
                  {COUNTRIES.map((c) => <option key={c}>{c}</option>)}
                </select>
              </Field>
              <Field label={" "} error={errors.min_country_pct?.message}><Suffix unit="%" reg={register("min_country_pct", { valueAsNumber: true })} /></Field>
              <Field label="Engagement min" error={errors.min_engagement_pct?.message}><Suffix unit="%" reg={register("min_engagement_pct", { valueAsNumber: true })} step="0.1" /></Field>
            </div>
            <Field label="Contenus interdits" group>
              <Chips values={values.forbidden ?? []} onChange={(v) => setValue("forbidden", v)} placeholder="+ Ajouter" tone="pink" />
            </Field>
          </Section>
        </div>

        <aside className="flex flex-col gap-8">
          <OverlayPreview src={overlayPreview} x={values.overlay_x} y={values.overlay_y} width={values.overlay_width}
                          label={values.source_platform?.toUpperCase()}
                          onMove={(x, y) => { setValue("overlay_x", x); setValue("overlay_y", y); }} />
          <div className="card-qc border-yellow/50 p-7">
            <div className="mb-5 flex items-baseline justify-between">
              <h3 className="title-lg text-[1.25rem]">Checklist avant de poster</h3>
              <span className="eyebrow">Auto</span>
            </div>
            <ul className="flex flex-col gap-4">
              {checklist(values, !!overlayPreview).map((item) => (
                <li key={item.label} className="flex gap-3">
                  <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-md bg-yellow"><Check className="size-4" /></span>
                  <span><span className="block font-semibold">{item.label}</span>{item.detail && <span className="text-sm text-muted-foreground">{item.detail}</span>}</span>
                </li>
              ))}
              {!checklist(values, !!overlayPreview).length && <li className="text-sm text-muted-foreground">Remplis les obligations : la checklist se construit toute seule.</li>}
            </ul>
          </div>
          <div className="card-qc grid grid-cols-2 gap-x-6 gap-y-5 p-7">
            <Money label="Par 1 000 vues" reg={register("rate_per_1k", { valueAsNumber: true })} error={errors.rate_per_1k?.message} olive />
            <Money label="Budget total" reg={register("budget_total", { valueAsNumber: true })} error={errors.budget_total?.message} />
            <Money label="Min / clip" reg={register("payout_min", { valueAsNumber: true })} error={errors.payout_min?.message} />
            <Money label="Max / clip" reg={register("payout_max", { valueAsNumber: true })} error={errors.payout_max?.message} />
          </div>
        </aside>
      </div>
    </form>
  );
}

const INPUT = "h-13 w-full rounded-2xl border border-line bg-secondary/60 px-4 text-[1.02rem] outline-none transition-colors focus:border-blue focus:bg-surface";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <fieldset className="card-qc flex flex-col gap-5 px-8 pt-6 pb-8">
      <legend className="-ml-2 px-2 font-display text-[1.25rem] font-bold">{title}</legend>
      {children}
    </fieldset>
  );
}

/** Un champ. `group` : plusieurs boutons (choix, puces) → un groupe nommé, pas un <label> (sinon le premier bouton
 *  prendrait tout le texte comme nom, et cliquer le titre le sélectionnerait). */
function Field({ label, hint, error, group, children }: {
  label: string; hint?: string; error?: string; group?: boolean; children: React.ReactNode;
}) {
  const content = (
    <>
      <span className="font-medium">{label}</span>
      {children}
      {hint && <span className="text-sm text-muted-foreground">{hint}</span>}
      <Err msg={error} />
    </>
  );
  return group ? (
    <div role="group" aria-label={label.trim() || undefined} className="flex flex-col gap-2">{content}</div>
  ) : (
    <label className="flex flex-col gap-2">{content}</label>
  );
}

const Err = ({ msg }: { msg?: string }) => (msg ? <span className="text-sm text-pink">{msg}</span> : null);

function Segmented({ value, onChange, options, mono }: { value: string; onChange: (v: string) => void; options: [string, string][]; mono?: boolean }) {
  return (
    <div className="flex h-13 gap-1 rounded-2xl border border-line bg-secondary/60 p-1">
      {options.map(([v, label]) => (
        <button key={v} type="button" onClick={() => onChange(v)}
                className={cn("flex-1 rounded-xl text-[0.95rem] transition-colors", mono && "font-mono tracking-wider",
                  value === v ? "bg-yellow font-semibold" : "text-muted-foreground hover:text-ink")}>
          {label}
        </button>
      ))}
    </div>
  );
}

function Suffix({ unit, reg, step = "1" }: { unit: string; reg: UseFormRegisterReturn; step?: string }) {
  return (
    <div className="relative">
      <input type="number" step={step} {...reg} className={cn(INPUT, "pr-10 font-mono")} />
      <span className="absolute top-1/2 right-4 -translate-y-1/2 text-muted-foreground">{unit}</span>
    </div>
  );
}

function LayoutCard({ title, detail, selected, onClick, disabled, split }: {
  title: string; detail: string; selected: boolean; onClick?: () => void; disabled?: boolean; split?: boolean;
}) {
  return (
    <button type="button" disabled={disabled} onClick={onClick} title={disabled ? "Le recadrage arrive au jalon M6" : undefined}
            className={cn("flex items-center gap-4 rounded-2xl border p-4 text-left transition-colors",
              selected ? "border-yellow bg-yellow-soft/50" : "border-line bg-secondary/50", disabled && "cursor-not-allowed opacity-50")}>
      <span className="flex h-16 w-10 shrink-0 flex-col overflow-hidden rounded-md bg-[#c9ccd6]">
        {split && <span className="h-1/3 bg-yellow" />}
      </span>
      <span><span className="block font-semibold">{title}</span><span className="text-sm text-muted-foreground">{detail}</span></span>
    </button>
  );
}

function Chips({ values, onChange, placeholder, normalize = (t) => t, tone }: {
  values: string[]; onChange: (v: string[]) => void; placeholder: string; normalize?: (t: string) => string; tone: "olive" | "pink";
}) {
  const [text, setText] = useState("");
  const add = () => {
    const raw = text.trim();
    const value = raw.replace(/^#+/, "") ? normalize(raw) : ""; // champ vide ou « # » seul : rien
    if (value && !values.includes(value)) onChange([...values, value]);
    setText("");
  };
  return (
    <div className="flex min-h-13 flex-wrap items-center gap-2 rounded-2xl border border-line bg-secondary/60 px-3 py-2">
      {values.map((v) => (
        <span key={v} className={cn("flex items-center gap-1 rounded-lg px-3 py-1",
          tone === "olive" ? "bg-yellow-soft font-mono text-olive" : "bg-pink-soft text-pink")}>
          {v}
          <button type="button" aria-label={`Retirer ${v}`} onClick={() => onChange(values.filter((x) => x !== v))}><X className="size-3.5" /></button>
        </span>
      ))}
      <input value={text} onChange={(e) => setText(e.target.value)} placeholder={placeholder} onBlur={add}
             onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); } }}
             className="min-w-40 flex-1 bg-transparent px-1 outline-none" />
    </div>
  );
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button type="button" onClick={() => onChange(!checked)}
            className="flex h-13 items-center justify-between rounded-2xl border border-line bg-secondary/60 px-4 text-left">
      {label}
      <span className={cn("grid size-6 place-items-center rounded-md border", checked ? "border-olive bg-olive text-white" : "border-line bg-surface")}>
        {checked && <Check className="size-4" />}
      </span>
    </button>
  );
}

function OverlayDrop({ file, onFile, onClear }: { file: string | null; onFile: (f: File) => void; onClear: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
         onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) onFile(f); }}
         className={cn("flex min-h-44 flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-yellow/70 bg-yellow-soft/30 p-6 text-center",
           over && "bg-yellow-soft")}>
      <Upload className="size-6 text-olive" />
      <p className="font-semibold">Overlay obligatoire</p>
      <p className="text-sm text-muted-foreground">
        {file ? file : "PNG transparent · "}
        {!file && <button type="button" className="underline" onClick={() => input.current?.click()}>glisse ou choisis un fichier</button>}
      </p>
      {file && (
        <div className="flex gap-3 text-sm">
          <button type="button" className="underline" onClick={() => input.current?.click()}>Remplacer</button>
          <button type="button" className="text-pink underline" onClick={onClear}>Retirer</button>
        </div>
      )}
      <input ref={input} type="file" accept="image/png,image/webp" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); }} />
    </div>
  );
}

/** Téléphone 9:16 : l'overlay se déplace à la souris ; sa position (fraction de 1080x1920) est enregistrée dans le brief. */
function OverlayPreview({ src, x, y, width, label, onMove }: {
  src: string | null; x: number; y: number; width: number; label?: string; onMove: (x: number, y: number) => void;
}) {
  const phone = useRef<HTMLDivElement>(null);
  const drag = (e: React.PointerEvent) => {
    const box = phone.current?.getBoundingClientRect();
    if (!box || !(e.buttons & 1)) return;
    const nx = Math.min(Math.max((e.clientX - box.left) / box.width - width / 2, 0), 1 - width);
    const ny = Math.min(Math.max((e.clientY - box.top) / box.height - 0.03, 0), 0.8);
    onMove(Number(nx.toFixed(3)), Number(ny.toFixed(3)));
  };
  return (
    <div className="card-qc p-7">
      <p className="eyebrow mb-4">Aperçu de l&apos;overlay</p>
      <div ref={phone} className="relative mx-auto aspect-[9/16] w-56 overflow-hidden rounded-[1.6rem] bg-ink select-none">
        <div className="absolute inset-x-0 top-0 h-1/3 bg-[#262b38]" />
        <div className="absolute inset-x-0 top-1/3 bottom-0 bg-[repeating-linear-gradient(135deg,#1b1f29_0_10px,#151820_10px_20px)]" />
        <p className="absolute inset-x-3 top-[55%] text-center font-display text-sm font-extrabold text-white">IL A RIEN <span className="text-yellow">VU</span> VENIR</p>
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element -- aperçu local
          <img src={src} alt="Overlay" draggable={false} onPointerDown={(e) => e.currentTarget.setPointerCapture(e.pointerId)} onPointerMove={drag}
               className="absolute cursor-grab active:cursor-grabbing" style={{ left: `${x * 100}%`, top: `${y * 100}%`, width: `${width * 100}%` }} />
        ) : (
          <span className="absolute rounded-md border border-dashed border-yellow/70 px-2 py-1 font-mono text-[0.6rem] text-yellow"
                style={{ left: `${x * 100}%`, top: `${y * 100}%` }}>OVERLAY{label ? ` ${label}` : ""}</span>
        )}
      </div>
      <p className="mt-4 text-center text-sm text-muted-foreground">
        {src ? "Glisse l'overlay pour choisir sa place. Elle sera la même sur tous les clips." : "Ajoute l'image de l'overlay pour la placer."}
      </p>
    </div>
  );
}

function Money({ label, reg, error, olive }: { label: string; reg: UseFormRegisterReturn; error?: string; olive?: boolean }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="flex items-baseline gap-1">
        <input type="number" step="0.01" min="0" {...reg} placeholder="—"
               className={cn("min-w-[2ch] max-w-full bg-transparent font-display text-[1.9rem] font-bold outline-none [field-sizing:content]", olive && "text-olive")} />
        <span className={cn("font-display text-[1.5rem] font-bold", olive && "text-olive")}>$</span>
      </span>
      <Err msg={error} />
    </label>
  );
}
