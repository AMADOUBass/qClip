"use client";

// Éditeur de clip (maquette 5) : transcription cliquable (corriger un mot ou toutes ses occurrences), aperçu 9:16
// en direct, layout, style des sous-titres, accroche, rendu du clip. Réglages → work/<id>/edits.json.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pause, Play, Smartphone, Sparkles, TriangleAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Preview } from "@/components/editor/preview";
import { PageHeader } from "@/components/page-header";
import { type EditorData, type EditorWord, type HookSuggestions, type Job, type Moments, type Peaks, type SubtitleStyle, api, media, post, put } from "@/lib/api";
import { useJobs } from "@/lib/events";
import { clock, eta } from "@/lib/format";
import { cn } from "@/lib/utils";

const STYLES: { key: SubtitleStyle; label: string }[] = [
  { key: "neon", label: "Néon jaune" },
  { key: "box", label: "Boîte" },
  { key: "outline", label: "Contour" },
  { key: "karaoke", label: "Karaoké" },
];

export function EditorView({ data, moments }: { data: EditorData; moments: Moments }) {
  const router = useRouter();
  const client = useQueryClient();
  const vid = moments.video_id;
  const key = ["editor", vid, data.window];
  const [video, setVideo] = useState<HTMLVideoElement | null>(null); // pour l'aperçu
  const player = useRef<HTMLVideoElement | null>(null); // pour piloter la lecture (saut, lecture, pause)
  const [playing, setPlaying] = useState(false);
  const [clipTime, setClipTime] = useState(0);
  const [safeZones, setSafeZones] = useState(false);
  const [hook, setHook] = useState(data.hook);
  const [zoom, setZoom] = useState(data.preview.zoom);
  const saveZoom = () => Math.abs(zoom - data.preview.zoom) > 0.001 && save.mutate({ zoom: Math.round(zoom * 100) / 100 });
  const fileStart = data.start - data.window_start;

  // Navigation : les clips gardés au tri (sinon tous les moments), du plus fort au plus faible.
  const kept = moments.moments.filter((m) => m.decision === "keep");
  const pool = kept.some((m) => m.window === data.window) ? kept : moments.moments;
  const index = pool.findIndex((m) => m.window === data.window);
  const goTo = (i: number) => pool[i] && router.replace(`/editor?vod=${vid}&w=${pool[i].window}`, { scroll: false });

  const save = useMutation({
    mutationFn: (changes: Record<string, unknown>) => put(`/api/vods/${vid}/moments/${data.window}`, changes),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: key });
      client.invalidateQueries({ queryKey: ["moments", vid] });
    },
    onError: (e) => toast.error(e.message),
  });
  const correct = useMutation({
    mutationFn: (body: { text: string; start?: number; old?: string }) =>
      post<EditorData>(`/api/vods/${vid}/moments/${data.window}/corrections`, body),
    onSuccess: (fresh, body) => {
      client.setQueryData(key, fresh);
      client.invalidateQueries({ queryKey: ["moments", vid] });
      toast.success(body.old ? `« ${body.old} » corrigé partout → « ${body.text} »` : `Corrigé → « ${body.text} »`);
    },
    onError: (e) => toast.error(e.message),
  });
  const render = useMutation({
    mutationFn: () => post(`/api/vods/${vid}/render`, { windows: [data.window] }),
    onSuccess: () => toast.success("Rendu lancé", { description: "Suivi dans la pastille en haut ; le clip arrive dans le pipeline." }),
    onError: (e) => toast.error(e.message),
  });

  // Temps du clip suivi à chaque image pendant la lecture (les sous-titres changent mot par mot).
  useEffect(() => {
    const v = player.current;
    if (!v || !playing) return;
    let frame = 0;
    const tick = () => {
      const t = v.currentTime - fileStart;
      if (t >= data.duration) {
        v.pause();
        v.currentTime = fileStart;
        setClipTime(0);
        return;
      }
      setClipTime(Math.max(0, t));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, fileStart, data.duration]);

  const seek = (t: number) => {
    const clamped = Math.min(Math.max(t, 0), data.duration - 0.05);
    if (player.current) player.current.currentTime = fileStart + clamped;
    setClipTime(clamped);
  };
  const toggle = () => {
    const v = player.current;
    if (!v) return;
    if (!v.paused) return v.pause();
    if (clipTime >= data.duration - 0.1) seek(0);
    v.play().catch(() => toast.error("Lecture impossible : la vidéo de la plage ne se charge pas"));
  };

  const failing = data.compliance.checks.filter((c) => !c.ok);
  const style = data.style;

  return (
    <>
      <PageHeader
        eyebrow={`${moments.campaign_name} — ${moments.title} / ${pool === kept ? "Clip" : "Moment"} ${index + 1} sur ${pool.length}${pool === kept ? (pool.length > 1 ? " gardés" : " gardé") : ""}`}
        title={data.title}
        search={false}
      >
        <span className="rounded-xl bg-secondary px-3 py-2 font-mono">{clock(data.duration)}</span>
        {data.compliance.ok ? (
          <span className="flex items-center gap-2 rounded-xl bg-blue-soft px-4 py-2 font-medium text-blue"><Check className="size-4" /> Conforme au brief</span>
        ) : (
          <span title={failing.map((c) => `${c.name} : ${c.detail}`).join("\n")}
                className="flex items-center gap-2 rounded-xl bg-orange-soft px-4 py-2 font-medium text-orange">
            <TriangleAlert className="size-4" /> {failing.length === 1 ? failing[0].detail : `${failing.length} points du brief`}
          </span>
        )}
        {!data.safety.ok && (
          <span className="flex items-center gap-2 rounded-xl bg-orange-soft px-4 py-2 font-medium text-orange">
            <TriangleAlert className="size-4" /> Démonétisation
          </span>
        )}
        <button type="button" disabled={index <= 0} onClick={() => goTo(index - 1)}
                className="h-12 rounded-2xl border border-line bg-surface px-5 font-medium disabled:opacity-40">← Clip précédent</button>
        <button type="button" disabled={index >= pool.length - 1} onClick={() => goTo(index + 1)}
                className="h-12 rounded-2xl border border-line bg-surface px-5 font-medium disabled:opacity-40">Clip suivant →</button>
      </PageHeader>

      {/* Vidéo source, invisible : l'aperçu la dessine sur un canvas. */}
      <video ref={(el) => { player.current = el; setVideo(el); }} src={media(data.video)} preload="auto" playsInline aria-hidden
             className="pointer-events-none fixed top-0 left-0 size-px opacity-0"
             onLoadedMetadata={(e) => { e.currentTarget.currentTime = fileStart; }}
             onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} />

      {!data.safety.ok && (
        <SafetyAlert data={data} pending={save.isPending} onShift={(s) => save.mutate({ start: data.start + s })} />
      )}

      <div className="mb-8 grid grid-cols-[minmax(0,1fr)_minmax(0,25rem)_minmax(0,1fr)] gap-8">
        <Transcript words={data.words} clipTime={clipTime} onSeek={seek} pending={correct.isPending}
                    onCorrect={(w, text, everywhere) => correct.mutate(everywhere
                      ? { old: bare(w.text), text: bare(text) } // le cœur garde la ponctuation de chaque occurrence
                      : { start: w.vod_start, text })} />

        <div>
          <Preview data={data} video={video} clipTime={clipTime} style={style} hook={hook} safeZones={safeZones} zoom={zoom} />
          <div className="mt-4 flex justify-center gap-3">
            <button type="button" onClick={() => setSafeZones(!safeZones)} aria-pressed={safeZones}
                    className={cn("flex h-12 items-center gap-2 rounded-2xl border px-4 font-medium",
                      safeZones ? "border-pink/40 bg-pink-soft text-pink" : "border-line bg-surface")}>
              <Smartphone className="size-4" /> Zones TikTok / Shorts
            </button>
            <button type="button" onClick={toggle} aria-label={playing ? "Pause" : "Lire le clip"}
                    className="grid size-12 place-items-center rounded-2xl bg-yellow">
              {playing ? <Pause className="size-5 fill-current" /> : <Play className="size-5 fill-current" />}
            </button>
          </div>
          <p className="mt-3 text-center text-muted-foreground">Aperçu en direct · aucun rendu nécessaire</p>
        </div>

        <div className="space-y-6">
          <section className="card-qc p-6">
            <h2 className="mb-4 font-display text-xl font-bold">Layout</h2>
            <div className="grid grid-cols-3 rounded-2xl bg-secondary p-1">
              {(["facecam", "blur", "crop"] as const).map((l) => (
                <button key={l} type="button" disabled={save.isPending} onClick={() => save.mutate({ layout: l })}
                        className={cn("h-11 rounded-xl font-medium", data.layout === l ? "bg-yellow" : "text-muted-foreground")}>
                  {l === "facecam" ? "Facecam" : l === "blur" ? "Flou" : "Recadrage"}
                </button>
              ))}
            </div>
            {data.preview.note && <p className="mt-3 text-sm text-orange">{noteLabel(data.preview.note)}</p>}
          </section>

          <section className="card-qc p-6">
            <h2 className="mb-4 font-display text-xl font-bold">Style des sous-titres</h2>
            <div className="grid grid-cols-2 gap-3">
              {STYLES.map((s) => (
                <button key={s.key} type="button" onClick={() => save.mutate({ style: s.key })} aria-pressed={style === s.key}
                        className={cn("rounded-2xl bg-ink px-4 py-4 text-center", style === s.key && "ring-2 ring-yellow")}>
                  <StyleSample style={s.key} highlight={data.subtitle.highlight} />
                  <span className="mt-1 block text-sm text-white/60">{s.label}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="card-qc p-6">
            <h2 className="mb-4 font-display text-xl font-bold">Accroche</h2>
            <input value={hook} maxLength={80} onChange={(e) => setHook(e.target.value)} aria-label="Accroche"
                   onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
                   onBlur={() => hook.trim() !== data.hook && save.mutate({ hook: hook.trim() || null })}
                   className="h-13 w-full rounded-2xl border border-line bg-secondary/60 px-4 uppercase outline-none focus:border-blue" />
            <p className="mt-2 text-sm text-muted-foreground">
              {data.hook_auto ? "Citation du clip choisie automatiquement · " : ""}affichée 3 s en haut · vide = automatique
            </p>
            <SuggestHooks vid={vid} window={data.window} onPick={(h) => { setHook(h); save.mutate({ hook: h }); }} />
            <div className="mt-5">
              <div className="mb-2 flex justify-between text-muted-foreground">
                <span>Variation anti-doublon (zoom)</span><span className="font-mono text-ink">{Math.round(zoom * 100)} %</span>
              </div>
              <input type="range" min={100} max={Math.round(data.preview.zoom_max * 100)} step={1} value={Math.round(zoom * 100)}
                     aria-label="Variation anti-doublon (zoom)" className="w-full accent-olive"
                     onChange={(e) => setZoom(Number(e.target.value) / 100)}
                     onPointerUp={() => saveZoom()} onKeyUp={() => saveZoom()} onBlur={() => saveZoom()} />
              <p className="mt-1 text-sm text-muted-foreground">
                Image légèrement agrandie (le texte n&apos;est pas touché) · défaut {Math.round(data.preview.zoom_default * 100)} %
              </p>
            </div>
          </section>

          <section className="rounded-[1.75rem] bg-yellow p-6">
            <button type="button" onClick={() => render.mutate()} disabled={render.isPending}
                    className="h-14 w-full rounded-2xl bg-ink text-lg font-semibold text-yellow disabled:opacity-60">Rendre le clip</button>
            <p className="mt-3 text-center font-medium">{eta(data.render_estimate_s)} · Intel Quick Sync</p>
            {data.rendered && (
              <a href={media(data.rendered)} target="_blank" rel="noreferrer" className="mt-2 block text-center text-sm underline">
                Voir le dernier rendu (avant ces réglages)
              </a>
            )}
          </section>
        </div>
      </div>

      <Timeline vid={vid} data={data} clipTime={clipTime} onSeek={seek} />
    </>
  );
}

/** « Proposer » : le LLM (4B) suggère 3 accroches ; rien n'est appliqué sans un clic (il invente parfois). */
function SuggestHooks({ vid, window, onPick }: { vid: string; window: number; onPick: (hook: string) => void }) {
  const [jobId, setJobId] = useState<number | null>(null);
  const { data: jobs } = useJobs();
  const job = jobId != null ? jobs?.find((j) => j.id === jobId) : undefined;
  const ask = useMutation({
    mutationFn: () => post<{ job: Job }>(`/api/vods/${vid}/moments/${window}/suggest`, {}),
    onSuccess: ({ job: j }) => setJobId(j.id),
    onError: (e) => toast.error(e.message),
  });
  const busy = ask.isPending || job?.status === "queued" || job?.status === "running";
  const result = job?.status === "done" ? (job.result as HookSuggestions) : null;
  return (
    <div className="mt-4">
      <button type="button" onClick={() => ask.mutate()} disabled={busy}
              className="flex h-10 items-center gap-2 rounded-xl border border-line bg-secondary px-4 text-sm font-medium disabled:opacity-60">
        <Sparkles className="size-4" />
        {busy ? (job?.status === "queued" ? "En file d'attente…" : "Le modèle réfléchit… (≈ 1 min 30)") : "Proposer des accroches (4B)"}
      </button>
      {job?.status === "error" && <p className="mt-2 text-sm text-pink">{job.error}</p>}
      {result && (
        <div className="mt-3">
          <div className="flex flex-wrap gap-2">
            {result.hooks.map((h) => (
              <button key={h} type="button" onClick={() => onPick(h)}
                      className="rounded-xl bg-yellow-soft px-3 py-1.5 text-left text-sm font-medium text-olive hover:bg-yellow">
                {h}
              </button>
            ))}
            {!result.hooks.length && <span className="text-sm text-muted-foreground">Aucune proposition utilisable (gros mots filtrés).</span>}
          </div>
          {result.title && <p className="mt-2 text-sm text-muted-foreground">Titre proposé : « {result.title} »</p>}
          <p className="mt-1 text-xs text-muted-foreground">Propositions du modèle ({result.seconds} s) : vérifie qu&apos;elles collent au clip avant de choisir.</p>
        </div>
      )}
    </div>
  );
}

const FLAG_LABEL ={ "gros mot": "Gros mot", violence: "Son violent", image: "Image violente" } as const;

/** Risque de démonétisation (safety.py) : ce qui est dit / entendu dans les 7 premières secondes, et le correctif. */
function SafetyAlert({ data, pending, onShift }: { data: EditorData; pending: boolean; onShift: (s: number) => void }) {
  const s = data.safety;
  const what = s.flags.map((f) => `${FLAG_LABEL[f.kind]} « ${f.detail} » à ${clock(f.at)}`);
  const checked = !!s.vision && !("error" in s.vision);
  return (
    <div className="mb-6 flex flex-wrap items-center gap-4 rounded-2xl border border-orange/30 bg-orange-soft px-5 py-4" role="alert">
      <TriangleAlert className="size-5 shrink-0 text-orange" />
      <p className="min-w-0 flex-1">
        <span className="font-semibold text-orange">{[...new Set(what)].slice(0, 3).join(" · ")}</span>
        <span className="block text-sm text-muted-foreground">
          {s.rule}{checked ? "" : " Images non vérifiées : regarde aussi le début."}
        </span>
      </p>
      {s.shift_s != null ? (
        <button type="button" disabled={pending} onClick={() => onShift(s.shift_s as number)}
                className="h-11 rounded-xl bg-orange px-4 font-semibold text-white disabled:opacity-60">
          Décaler le début de {s.shift_s.toLocaleString("fr-FR")} s
        </button>
      ) : (
        <span className="text-sm text-muted-foreground">Aucun décalage possible sans passer sous la durée min du brief.</span>
      )}
    </div>
  );
}

/** « layout facecam impossible (caméra plein cadre …) : repli sur blur » → phrase pour l'écran. */
function noteLabel(note: string) {
  if (note.includes("plein cadre")) return "Facecam impossible ici : la caméra occupe tout l'écran. Le clip sera rendu en Flou.";
  if (note.includes("aucune webcam")) return "Aucune webcam détectée dans ce passage : le clip sera rendu en Flou.";
  return note;
}

function StyleSample({ style, highlight }: { style: SubtitleStyle; highlight: string }) {
  const word = "MOT";
  const common = "font-display text-2xl font-extrabold";
  if (style === "box") return <span className={cn(common, "rounded-lg px-2 text-ink")} style={{ background: highlight }}>{word}</span>;
  if (style === "outline") return <span className={cn(common, "text-blue")} style={{ WebkitTextStroke: `1px ${highlight}` }}>{word}</span>;
  if (style === "karaoke") return <span className={common} style={{ background: `linear-gradient(90deg, ${highlight} 55%, #fff 55%)`, WebkitBackgroundClip: "text", color: "transparent" }}>{word}</span>;
  return <span className={common} style={{ color: highlight }}>{word}</span>;
}

function Transcript({ words, clipTime, onSeek, onCorrect, pending }: {
  words: EditorWord[]; clipTime: number; onSeek: (t: number) => void; pending: boolean;
  onCorrect: (w: EditorWord, text: string, everywhere: boolean) => void;
}) {
  const [open, setOpen] = useState<number | null>(null);
  const [text, setText] = useState("");
  const unsure = words.map((w, i) => ({ w, i })).filter(({ w }) => w.unsure);
  const edit = (i: number) => {
    setOpen(i);
    setText(words[i].text);
    onSeek(words[i].start);
  };
  const same = (i: number) => words.filter((w) => bare(w.text).toLowerCase() === bare(words[i].text).toLowerCase()).length;
  const submit = (everywhere: boolean) => {
    if (open == null || !text.trim() || text.trim() === words[open].text) return setOpen(null);
    onCorrect(words[open], text.trim(), everywhere);
    setOpen(null);
  };

  return (
    <section className="card-qc self-start p-6">
      <div className="mb-4 flex items-baseline justify-between">
        <h2 className="font-display text-xl font-bold">Transcription</h2>
        <span className="eyebrow">Clique un mot</span>
      </div>
      <p className="flex flex-wrap gap-x-1 gap-y-1.5 text-[1.1rem]">
        {words.map((w, i) => (
          <span key={`${w.vod_start}-${i}`} className="relative">
            <button type="button" onClick={() => edit(i)}
                    title={w.confidence != null ? `confiance ${Math.round(w.confidence * 100)} %` : undefined}
                    className={cn("rounded-lg px-1.5 py-0.5 transition-colors hover:bg-secondary",
                      clipTime >= w.start && clipTime < w.end && "bg-yellow",
                      w.unsure && "underline decoration-orange decoration-wavy decoration-2 underline-offset-4")}>
              {w.text}
            </button>
            {open === i && (
              <span className="absolute top-full left-0 z-20 mt-2 w-72 rounded-2xl border border-line bg-surface p-3 shadow-lg">
                <input autoFocus value={text} onChange={(e) => setText(e.target.value)} aria-label="Mot corrigé"
                       onKeyDown={(e) => { if (e.key === "Enter") submit(false); if (e.key === "Escape") setOpen(null); }}
                       className="mb-2 h-11 w-full rounded-xl border border-line bg-secondary/60 px-3 outline-none focus:border-blue" />
                <span className="flex gap-2">
                  <button type="button" disabled={pending} onClick={() => submit(false)} className="h-10 flex-1 rounded-xl bg-yellow font-semibold">Ce mot</button>
                  <button type="button" disabled={pending} onClick={() => submit(true)} className="h-10 flex-1 rounded-xl border border-line bg-secondary font-medium">
                    Partout ({same(i)})
                  </button>
                </span>
              </span>
            )}
          </span>
        ))}
      </p>
      {unsure.length > 0 && (
        <div className="mt-6 rounded-2xl border border-orange/30 bg-orange-soft p-4">
          <p className="mb-2 flex items-center gap-2 font-semibold text-orange">
            <TriangleAlert className="size-4" /> {unsure.length} mot{unsure.length > 1 ? "s" : ""} peu sûr{unsure.length > 1 ? "s" : ""}
          </p>
          <p className="mb-3 text-sm text-muted-foreground">Clique-les pour vérifier à l&apos;écoute et corriger.</p>
          <div className="flex flex-wrap gap-2">
            {unsure.map(({ w, i }) => (
              <button key={i} type="button" onClick={() => edit(i)} className="rounded-xl bg-orange px-3 py-1.5 font-semibold text-white">
                « {w.text} »
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

/** Mot sans la ponctuation autour (comme correct_everywhere dans qclip/edits.py). */
const bare = (t: string) => t.replace(/^[.,!?…:;«»"']+|[.,!?…:;«»"']+$/g, "");

function Timeline({ vid, data, clipTime, onSeek }: { vid: string; data: EditorData; clipTime: number; onSeek: (t: number) => void }) {
  const { data: peaks } = useQuery({
    queryKey: ["peaks", vid, data.window],
    queryFn: () => api<Peaks>(`/api/vods/${vid}/moments/${data.window}/peaks`),
    staleTime: Infinity,
  });
  const BARS = 150;
  const fileStart = data.start - data.window_start;
  const values = Array.from({ length: BARS }, (_, i) => {
    if (!peaks?.peaks.length) return 0.3;
    const per = peaks.peaks.length / peaks.duration;
    const a = Math.floor((fileStart + (i / BARS) * data.duration) * per);
    const b = Math.max(a + 1, Math.floor((fileStart + ((i + 1) / BARS) * data.duration) * per));
    return Math.max(0, ...peaks.peaks.slice(a, b));
  });
  const ticks = Array.from({ length: Math.floor(data.duration / 10) + 1 }, (_, i) => i * 10).filter((t) => data.duration - t > 3);
  return (
    <section className="card-qc px-6 pt-5 pb-4">
      <div className="relative h-24 cursor-pointer select-none" role="group" aria-label="Ligne de temps du clip" onPointerDown={(e) => {
        const box = e.currentTarget.getBoundingClientRect();
        onSeek(((e.clientX - box.left) / box.width) * data.duration);
      }}>
        <div className="absolute inset-0 flex items-center gap-[3px]">
          {values.map((v, i) => (
            <span key={i} className={cn("flex-1 rounded-full", ((i + 0.5) / BARS) * data.duration <= clipTime ? "bg-yellow" : "bg-[#cfd1d9]")}
                  style={{ height: `${Math.round(15 + v * 75)}%` }} />
          ))}
        </div>
        <span className="pointer-events-none absolute inset-y-0 w-0.5 bg-blue" style={{ left: `${(clipTime / data.duration) * 100}%` }} />
      </div>
      <div className="relative mt-3 h-5 font-mono text-sm text-muted-foreground">
        {[...ticks, data.duration].map((t, i, all) => (
          <span key={t} className={cn("absolute", i === 0 ? "" : i === all.length - 1 ? "-translate-x-full" : "-translate-x-1/2")}
                style={{ left: `${(t / data.duration) * 100}%` }}>{clock(t)}</span>
        ))}
      </div>
    </section>
  );
}
