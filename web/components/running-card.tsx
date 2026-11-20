"use client";

// « EN COURS SUR TA MACHINE » (maquette 1) : étapes de la tâche, radar de la VOD, temps restant, RAM.

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { ErrorCard } from "@/components/states";
import { type Job, type SystemStatus, api } from "@/lib/api";
import { useJobs } from "@/lib/events";
import { eta } from "@/lib/format";
import { cn } from "@/lib/utils";

const PROCESS_STAGES = ["repérage", "téléchargement", "séparation", "transcription", "détection"];

type VodLite = { title: string; radar: { chat: number[]; audio: number[] }; windows: { start: number; end: number }[]; duration: number };

export function RunningCard() {
  const { data: jobs } = useJobs();
  const job = jobs?.find((j) => j.status === "running") ?? jobs?.find((j) => j.status === "queued");
  const failed = jobs?.[0]?.status === "error" ? jobs[0] : undefined; // la dernière tâche a échoué
  const { data: system } = useQuery({ queryKey: ["system"], queryFn: () => api<SystemStatus>("/api/system") });
  const vid = job?.video_id;
  const { data: vod } = useQuery({
    queryKey: ["vod", vid],
    queryFn: () => api<VodLite>(`/api/vods/${vid}`),
    enabled: !!vid,
    retry: false, // 404 tant que le repérage n'a rien produit
  });

  if (!job) return failed ? <ErrorCard job={failed} /> : null;
  const stages = job.kind === "process" ? PROCESS_STAGES : [];
  return (
    <Link href={vid ? `/vod/${vid}` : "/vod"} className="card-qc mb-10 grid grid-cols-[minmax(0,1.1fr)_minmax(0,1.4fr)_auto] items-center gap-8 border-blue/30 p-8">
      <div className="min-w-0">
        <p className="mb-3 flex items-center gap-2 font-mono text-[0.78rem] tracking-[0.14em] text-blue uppercase">
          <span className="size-2.5 animate-pulse rounded-full bg-blue" /> En cours sur ta machine
        </p>
        <p className="title-lg mb-4 truncate">{vod?.title ?? job.label}</p>
        <div className="flex flex-wrap gap-2">
          {stages.length ? stages.map((s) => <StageChip key={s} name={s} job={job} />) : (
            <span className="rounded-full bg-blue px-3 py-1.5 text-sm text-white">{job.step || "Démarrage…"}</span>
          )}
        </div>
      </div>
      <Waveform vod={vod} />
      <div className="flex gap-8">
        <div>
          <p className="eyebrow mb-1">Restant</p>
          <p className="font-display text-4xl font-bold text-blue">{eta(job.eta_s) || "—"}</p>
        </div>
        <div>
          <p className="eyebrow mb-1">RAM</p>
          <p className="font-display text-4xl font-bold">{system ? `${system.ram_used_gb.toLocaleString("fr-FR")}/${Math.round(system.ram_total_gb)} Go` : "—"}</p>
        </div>
      </div>
    </Link>
  );
}

function StageChip({ name, job }: { name: string; job: Job }) {
  const done = name in job.stage_times && job.stage !== name;
  const active = job.stage === name;
  const pct = active && job.progress ? Math.round((job.progress[0] / job.progress[1]) * 100) : null;
  const label = name.charAt(0).toUpperCase() + name.slice(1);
  return (
    <span className={cn("rounded-full px-3 py-1.5 text-sm",
      done && "bg-blue-soft text-blue", active && "bg-blue text-white", !done && !active && "bg-secondary text-muted-foreground")}>
      {label}{done && " ✓"}{pct != null && ` ${pct} %`}
    </span>
  );
}

/** Barres du chat de la VOD (bleu) avec les zones repérées en jaune ; grisé sans données. */
function Waveform({ vod }: { vod?: VodLite }) {
  const bars = 64;
  const chat = vod?.radar.chat ?? [];
  const values = Array.from({ length: bars }, (_, i) => {
    if (!chat.length) return 0.25 + 0.2 * Math.abs(Math.sin(i * 1.7));
    const a = Math.floor((i / bars) * chat.length);
    const b = Math.max(a + 1, Math.floor(((i + 1) / bars) * chat.length));
    return Math.max(0.12, Math.max(...chat.slice(a, b)));
  });
  const zone = (i: number) =>
    vod?.windows.some((w) => Math.floor((w.start / vod.duration) * bars) === i) ?? false;
  return (
    <div className="flex h-24 items-center gap-[3px]" aria-hidden>
      {values.map((v, i) => (
        <span key={i} className={cn("w-1.5 rounded-full", zone(i) ? "bg-yellow" : chat.length ? "bg-blue" : "bg-secondary")}
              style={{ height: `${zone(i) ? 100 : Math.round(v * 80) + 10}%` }} />
      ))}
    </div>
  );
}
