"use client";

// Écran VOD — radar et traitement (maquette 3). Données : /api/vods/<id> (état sur disque) + la tâche en direct
// (SSE) pour la progression, le temps restant et l'étape en cours. Rechargé toutes les 4 s pendant l'analyse.

import { useMutation, useQuery } from "@tanstack/react-query";
import { Check } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import { MetaChip, PageHeader } from "@/components/page-header";
import { ApiDown, ErrorCard } from "@/components/states";
import { AnalyzeForm } from "@/components/vod/analyze-form";
import { Radar, type ZoneState } from "@/components/vod/radar";
import { ApiError, type Job, type Vod, type VodStage, api, post } from "@/lib/api";
import { useJobs } from "@/lib/events";
import { clock, eta, hm, span } from "@/lib/format";
import { cn } from "@/lib/utils";

const ORDER: VodStage["key"][] = ["repérage", "téléchargement", "séparation", "transcription", "détection"];
const LEVEL = { waiting: 0, fetched: 1, audio: 2, transcribed: 3 } as const;
const TARGET: Partial<Record<VodStage["key"], number>> = { téléchargement: 1, séparation: 2, transcription: 3 };
const SCOUT_LABELS: Record<string, string> = {
  "métadonnées": "Informations de la VOD",
  "chat (TwitchDownloaderCLI)": "Replay du chat téléchargé",
  "audio basse qualité (yt-dlp)": "Audio basse qualité de toute la VOD",
  "volume RMS par seconde": "Volume calculé seconde par seconde",
  "score + fenêtres": "Pics de chat et de volume calculés",
};

/** Dernière tâche d'analyse de cette VOD (en cours, en attente ou terminée). */
function useVodJob(vid: string | null) {
  const { data: jobs } = useJobs();
  return jobs?.find((j) => j.kind === "process" && j.video_id === vid) ?? null;
}

export function VodView({ vid }: { vid: string }) {
  const job = useVodJob(vid);
  const active = job && (job.status === "running" || job.status === "queued") ? job : null;
  const { data: vod, error } = useQuery({
    queryKey: ["vod", vid],
    queryFn: () => api<Vod>(`/api/vods/${vid}`),
    retry: false,
    refetchInterval: active ? 4000 : false,
  });
  if (error) {
    if (error instanceof ApiError && error.status === 404 && active) return <Scouting job={active} />;
    if (error instanceof ApiError && error.status === 404) return <UnknownVod />;
    return <ApiDown message={error.message} />;
  }
  if (!vod) return active ? <Scouting job={active} /> : <div className="card-qc h-96 animate-pulse" />;
  return <VodScreen vod={vod} job={job} />;
}

function VodScreen({ vod, job }: { vod: Vod; job: Job | null }) {
  const running = job?.status === "running" ? job : null;
  const liveStage = running?.stage as VodStage["key"] | undefined;
  const liveIndex = liveStage ? ORDER.indexOf(liveStage) : -1;

  // État de chaque grande étape : la tâche en direct fait foi (avant = fait, après = en attente).
  const stages = vod.stages.map((s, i) => {
    const live = running && s.key === liveStage;
    // Sans tâche en direct, une étape à moitié faite est interrompue, pas « en cours ».
    const state: VodStage["state"] = liveIndex < 0 ? (s.state === "running" ? "waiting" : s.state)
      : i < liveIndex ? "done" : live ? "running" : "waiting";
    const progress = live && running?.progress ? running.progress : ([s.done ?? 0, s.total ?? 0] as [number, number]);
    const seconds = s.seconds ?? running?.stage_times[s.key] ?? job?.stage_times[s.key];
    const left = state === "done" ? 0 : live ? (running?.eta_s ?? s.estimate_s ?? 0) : (s.estimate_s ?? 0);
    return { ...s, state, progress, seconds, left, live: !!live };
  });

  // Zones : « traitée » = a passé l'étape en cours ; « en cours » = la suivante dans l'ordre de traitement (rang).
  const target = (liveStage && TARGET[liveStage]) ?? 3;
  const byRank = [...vod.windows].sort((a, b) => a.rank - b.rank);
  const firstPending = byRank.find((w) => LEVEL[w.state] < target)?.rank;
  const zoneState = (rank: number): ZoneState => {
    const w = byRank.find((x) => x.rank === rank);
    if (w && LEVEL[w.state] >= target) return "done";
    return running && liveStage && TARGET[liveStage] && rank === firstPending ? "current" : "waiting";
  };
  const failed = job?.status === "error" ? job : null;

  return (
    <>
      <PageHeader
        eyebrow={`${vod.campaign_name} / VOD`}
        title={vod.title}
        search={false}
        job={false}
        meta={<>
          {vod.platform && <MetaChip>{vod.platform}</MetaChip>}
          <MetaChip>{vod.language}</MetaChip>
          <MetaChip>{hm(vod.duration)}{vod.duration >= 3600 ? " min" : ""}</MetaChip>
          {vod.chat_messages > 0 && <MetaChip>{vod.chat_messages.toLocaleString("fr-FR")} messages</MetaChip>}
          {vod.source_rule && (
            <span className="rounded-lg bg-yellow-soft px-3 py-1.5 text-[0.9rem] font-medium text-olive">Règle de source : {vod.source_rule} ✓</span>
          )}
        </>}
      >
        <AnalyzeForm campaign={vod.campaign} />
      </PageHeader>

      {failed && <ErrorCard job={failed} />}
      <Radar vod={vod} zoneState={zoneState} />

      <section className="mb-10 grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_minmax(0,1fr)] gap-6">
        <ScoutCard stage={stages[0]} />
        <ProcessCard stages={stages.slice(1)} job={running} />
        <RemainingCard vod={vod} job={job} left={stages.reduce((sum, s) => sum + s.left, 0)} />
      </section>

      <Zones vod={vod} zoneState={zoneState} />
    </>
  );
}

type LiveStage = VodStage & { progress: [number, number]; seconds?: number; left: number; live: boolean };

function Badge({ state, children }: { state: "done" | "running" | "waiting"; children: React.ReactNode }) {
  return (
    <span className={cn("flex shrink-0 items-center gap-2 rounded-lg px-3 py-1 font-mono text-[0.78rem] whitespace-nowrap uppercase",
      state === "done" && "bg-blue-soft text-blue", state === "running" && "text-blue", state === "waiting" && "bg-secondary text-muted-foreground")}>
      {state === "running" && <span className="size-2 animate-pulse rounded-full bg-blue" />}
      {children}
    </span>
  );
}

function ScoutCard({ stage }: { stage: LiveStage }) {
  const measured = (stage.seconds ?? 0) >= 1;
  return (
    <div className="card-qc p-8">
      <div className="mb-6 flex items-center justify-between gap-3">
        <h2 className="min-w-0 font-display text-[1.3rem] font-bold">1 · Repérage</h2>
        <Badge state="done">Terminé{measured ? ` · ${span(stage.seconds ?? 0)}` : ""}</Badge>
      </div>
      <ul className="space-y-4">
        {(stage.steps ?? []).map((s) => (
          <li key={s.name} className="flex items-center gap-4">
            <DoneDot />
            <span className="flex-1">{SCOUT_LABELS[s.name] ?? s.name}</span>
            <span className="font-mono text-sm text-muted-foreground">{s.seconds >= 1 ? span(s.seconds) : "—"}</span>
          </li>
        ))}
      </ul>
      {!measured && <p className="mt-5 text-sm text-muted-foreground">Repris depuis le cache : temps d&apos;origine non conservé.</p>}
    </div>
  );
}

function ProcessCard({ stages, job }: { stages: LiveStage[]; job: Job | null }) {
  const allDone = stages.every((s) => s.state === "done");
  const running = stages.some((s) => s.state === "running");
  const started = stages.some((s) => s.state === "done" || s.progress[0] > 0);
  const total = stages.reduce((sum, s) => sum + (s.seconds ?? 0), 0);
  const elapsed = job ? job.elapsed_s - (job.stage_times["repérage"] ?? 0) : 0;
  return (
    <div className={cn("card-qc p-8", running && "border-blue/30")}>
      <div className="mb-6 flex items-center justify-between gap-3">
        <h2 className="min-w-0 font-display text-[1.3rem] font-bold">2 · Traitement des zones</h2>
        {allDone ? <Badge state="done">Terminé{total >= 1 ? ` · ${span(total)}` : ""}</Badge>
          : running ? <Badge state="running">En cours{elapsed > 0 ? ` · ${span(elapsed)}` : ""}</Badge>
          : <Badge state="waiting">{started ? "Interrompu" : "En attente"}</Badge>}
      </div>
      <ol className="space-y-5">
        {stages.map((s, i) => <StageRow key={s.key} stage={s} index={i + 1} step={s.live ? job?.step : undefined} />)}
      </ol>
    </div>
  );
}

function StageRow({ stage, index, step }: { stage: LiveStage; index: number; step?: string }) {
  const [done, total] = stage.progress;
  if (stage.state === "done") {
    return (
      <li className="flex items-center gap-4">
        <DoneDot />
        <span className="flex-1">{stage.name}</span>
        <span className="font-mono text-sm text-muted-foreground">{(stage.seconds ?? 0) >= 1 ? span(stage.seconds ?? 0) : ""}</span>
      </li>
    );
  }
  if (stage.state === "running") {
    const countable = total > 1;
    return (
      <li>
        <div className="flex items-center gap-4">
          <span className="grid size-8 shrink-0 place-items-center rounded-full bg-blue font-mono text-sm text-white">{index}</span>
          <span className="flex-1 font-medium">{stage.name}</span>
          <span className="font-mono text-sm text-blue">{countable && `${done}/${total} · `}{eta(stage.left) || "…"}</span>
        </div>
        <div className="mt-3 ml-12">
          {countable && (
            <div className="flex h-2 gap-[3px] overflow-hidden rounded-full bg-secondary" aria-label={`${done} sur ${total}`}>
              {Array.from({ length: total }, (_, i) => <span key={i} className={cn("flex-1", i < done ? "bg-blue" : "bg-transparent")} />)}
            </div>
          )}
          <p className="mt-2 text-sm text-muted-foreground">
            {countable ? `Zone ${Math.min(done + 1, total)} sur ${total}` : "En cours"}{step ? ` · ${step}` : ""}
          </p>
        </div>
      </li>
    );
  }
  return (
    <li className="flex items-center gap-4 text-muted-foreground">
      <span className="grid size-8 shrink-0 place-items-center rounded-full bg-secondary font-mono text-sm">{index}</span>
      <span className="flex-1">{stage.name}</span>
      <span className="font-mono text-sm">
        {[total > 1 && done > 0 && `${done}/${total}`, stage.left > 0 && eta(stage.left)].filter(Boolean).join(" · ")}
      </span>
    </li>
  );
}

function DoneDot() {
  return <span className="grid size-8 shrink-0 place-items-center rounded-full bg-blue-soft text-blue"><Check className="size-4" /></span>;
}

function RemainingCard({ vod, job, left }: { vod: Vod; job: Job | null; left: number }) {
  const resume = useMutation({
    mutationFn: () => post(`/api/campaigns/${vod.campaign}/vods`, { url: vod.url }),
    onSuccess: () => toast.success("Analyse relancée : les étapes déjà faites sont réutilisées"),
    onError: (e) => toast.error(e.message),
  });
  const sortHref = `/sort?vod=${vod.video_id}`;
  const finished = vod.candidates > 0 && vod.stages.every((s) => s.state === "done");
  const dark = "mt-auto flex h-14 items-center justify-center rounded-2xl bg-ink px-6 font-semibold text-yellow";

  if (job?.status === "running" || job?.status === "queued") {
    return (
      <div className="flex flex-col rounded-[1.75rem] bg-yellow p-8">
        <p className="mb-3 font-mono text-[0.78rem] tracking-[0.14em] uppercase">
          {job.status === "queued" ? "En file d'attente" : "Temps restant estimé"}
        </p>
        <p className="mb-5 font-display text-[3.4rem] leading-none font-extrabold">{job.status === "queued" ? "—" : eta(left) || "…"}</p>
        <p className="mb-6 font-medium">
          {job.status === "queued"
            ? "Une autre tâche tourne : celle-ci partira juste après (une seule à la fois sur ta machine)."
            : `${vod.ready_windows} zone${vod.ready_windows > 1 ? "s" : ""} sur ${vod.windows.length} déjà transcrite${vod.ready_windows > 1 ? "s" : ""}. Les moments seront prêts à trier après la détection.`}
        </p>
        {vod.candidates > 0
          ? <Link href={sortHref} className={dark}>Trier les {vod.candidates} moments déjà prêts →</Link>
          : <span className={cn(dark, "opacity-40")}>Tri disponible après la détection</span>}
      </div>
    );
  }
  if (finished) {
    return (
      <div className="flex flex-col rounded-[1.75rem] bg-yellow p-8">
        <p className="mb-3 font-mono text-[0.78rem] tracking-[0.14em] uppercase">Analyse terminée</p>
        <p className="mb-5 font-display text-[3.4rem] leading-none font-extrabold">
          {vod.candidates} <span className="text-[1.6rem]">moments</span>
        </p>
        <p className="mb-6 font-medium">Prêts à trier, les plus forts d&apos;abord. Garde ou jette au clavier, puis lance le rendu des gardés.</p>
        <Link href={sortHref} className={dark}>Trier {vod.candidates} moments →</Link>
      </div>
    );
  }
  return (
    <div className="card-qc flex flex-col p-8">
      <p className="eyebrow mb-3">Analyse interrompue</p>
      <p className="mb-6 text-muted-foreground">
        {vod.ready_windows} zone{vod.ready_windows > 1 ? "s" : ""} sur {vod.windows.length} transcrite{vod.ready_windows > 1 ? "s" : ""}.
        Relance l&apos;analyse : ce qui est déjà fait est réutilisé.
      </p>
      {job?.status === "error" ? (
        <p className="mt-auto text-sm text-muted-foreground">La cause et « Réessayer » sont dans la carte d&apos;erreur, en haut.</p>
      ) : (
        <button type="button" disabled={resume.isPending} onClick={() => resume.mutate()}
                className="mt-auto h-14 rounded-2xl bg-yellow font-semibold disabled:opacity-60">Reprendre l&apos;analyse</button>
      )}
    </div>
  );
}

function Zones({ vod, zoneState }: { vod: Vod; zoneState: (rank: number) => ZoneState }) {
  const zones = [...vod.windows].sort((a, b) => a.rank - b.rank).map((w) => ({ ...w, zs: zoneState(w.rank) }));
  const n = (s: ZoneState) => zones.filter((z) => z.zs === s).length;
  const sortable = vod.candidates > 0;
  return (
    <section>
      <div className="mb-4 flex items-baseline justify-between">
        <h2 className="title-lg">Zones</h2>
        <p className="text-muted-foreground">
          {n("done")} traitée{n("done") > 1 ? "s" : ""} · {n("current")} en cours · {n("waiting")} en attente
        </p>
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(8.5rem,1fr))] gap-3">
        {zones.map((z) => {
          const tile = cn("block rounded-2xl border px-4 py-3",
            z.zs === "done" && "border-blue/25 bg-blue-soft text-blue",
            z.zs === "current" && "border-yellow bg-yellow-soft text-olive",
            z.zs === "waiting" && "border-line bg-surface")
          const body = (
            <>
              <span className="block text-lg font-semibold">#{String(z.rank).padStart(2, "0")}</span>
              <span className={cn("font-mono text-sm", z.zs === "waiting" ? "text-muted-foreground" : "")}>{clock(z.start)}</span>
            </>
          );
          return sortable && z.zs === "done"
            ? <Link key={z.rank} href={`/sort?vod=${vod.video_id}&w=${z.rank}`} className={cn(tile, "transition-shadow hover:shadow-md")} title="Ouvrir ce moment dans le tri">{body}</Link>
            : <div key={z.rank} className={tile}>{body}</div>;
        })}
      </div>
    </section>
  );
}

/** Pendant le repérage, avant que scout.json existe : ce que la tâche a déjà fait (lignes « étape — 1,2 s »). */
export function Scouting({ job }: { job: Job }) {
  const done = job.logs.flatMap((line) => {
    const m = /^(.+) — ([\d.]+) s$/.exec(line);
    return m && SCOUT_LABELS[m[1]] ? [{ name: SCOUT_LABELS[m[1]], seconds: Number(m[2]) }] : [];
  });
  return (
    <>
      <PageHeader eyebrow="VOD / ANALYSE" title={job.label.replace(/^Analyse de /, "")} search={false} job={false} />
      <div className="card-qc max-w-2xl border-blue/30 p-8">
        <div className="mb-6 flex items-center justify-between gap-3">
          <h2 className="min-w-0 font-display text-[1.3rem] font-bold">1 · Repérage</h2>
          {job.status === "queued" ? <Badge state="waiting">En file d&apos;attente</Badge> : <Badge state="running">En cours · {span(job.elapsed_s)}</Badge>}
        </div>
        <ul className="space-y-4">
          {done.map((s) => (
            <li key={s.name} className="flex items-center gap-4">
              <DoneDot /><span className="flex-1">{s.name}</span>
              <span className="font-mono text-sm text-muted-foreground">{s.seconds >= 1 ? span(s.seconds) : "—"}</span>
            </li>
          ))}
          {job.status === "running" && job.step && !done.some((s) => s.name === SCOUT_LABELS[job.step]) && (
            <li className="flex items-center gap-4">
              <span className="size-8 shrink-0 animate-pulse rounded-full bg-blue" />
              <span className="flex-1 font-medium">{SCOUT_LABELS[job.step] ?? job.step}…</span>
            </li>
          )}
        </ul>
        <p className="mt-6 text-sm text-muted-foreground">
          qClip lit le chat et le volume de toute la VOD pour trouver les zones fortes, puis ne télécharge que celles-là.
        </p>
      </div>
    </>
  );
}

function UnknownVod() {
  return (
    <>
      <PageHeader eyebrow="VOD" title="VOD introuvable" />
      <div className="card-qc max-w-2xl p-8">
        <p className="mb-6 text-muted-foreground">Cette VOD n&apos;a pas (encore) été repérée sur cette machine.</p>
        <Link href="/vod/new" className="inline-flex h-12 items-center rounded-2xl bg-yellow px-6 font-semibold">Analyser une VOD</Link>
      </div>
    </>
  );
}
