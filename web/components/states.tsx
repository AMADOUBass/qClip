"use client";

// États vides et erreurs (maquette 7).

import { useMutation } from "@tanstack/react-query";
import { CircleAlert, Copy } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import { type Job, post } from "@/lib/api";

/** « Aucune campagne pour l'instant » avec le radar. */
export function EmptyCampaigns() {
  return (
    <div className="card-qc mx-auto max-w-3xl p-12 text-center">
      <p className="eyebrow mb-8 text-left">Tableau de bord · vide</p>
      <RadarIllustration />
      <h2 className="title-lg mt-8 mb-4">Aucune campagne pour l&apos;instant</h2>
      <p className="mx-auto mb-8 max-w-md text-muted-foreground">
        Rejoins une campagne de clipping sur Content Rewards, puis colle son brief ici. qClip en tire les règles à
        respecter.
      </p>
      <div className="flex justify-center gap-3">
        <Link href="/campaigns/new" className="flex h-12 items-center rounded-2xl bg-yellow px-6 font-semibold">Créer un brief</Link>
        <a href="https://whop.com/discover/" target="_blank" rel="noreferrer"
           className="flex h-12 items-center rounded-2xl border border-line bg-secondary px-6 font-medium">
          Trouver une campagne ↗
        </a>
      </div>
    </div>
  );
}

function RadarIllustration() {
  return (
    <svg viewBox="0 0 280 280" className="mx-auto size-56" aria-hidden>
      <defs>
        <linearGradient id="sweep" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--yellow)" stopOpacity="0.35" />
          <stop offset="1" stopColor="var(--yellow)" stopOpacity="0" />
        </linearGradient>
      </defs>
      {[138, 96, 54].map((r) => <circle key={r} cx="140" cy="140" r={r} fill="none" stroke="var(--line)" strokeWidth="2" />)}
      <line x1="2" y1="140" x2="278" y2="140" stroke="var(--line)" strokeWidth="2" />
      <line x1="140" y1="2" x2="140" y2="278" stroke="var(--line)" strokeWidth="2" />
      <path d="M140 140 L262 210 A138 138 0 0 1 180 272 Z" fill="url(#sweep)" />
      <rect x="180" y="66" width="30" height="52" rx="8" fill="var(--yellow)" />
      <rect x="72" y="166" width="22" height="38" rx="6" fill="none" stroke="var(--blue)" strokeWidth="3" />
      <rect x="196" y="182" width="16" height="28" rx="5" fill="none" stroke="#b3ad9f" strokeWidth="3" />
      <circle cx="140" cy="140" r="7" fill="var(--yellow)" />
    </svg>
  );
}

/** Erreur récupérable d'une tâche (ex. « Téléchargement Kick bloqué ») : message clair + actions. */
export function ErrorCard({ job, onRetry }: { job: Job; onRetry?: () => void }) {
  const retry = useMutation({
    mutationFn: () => post(`/api/campaigns/${job.campaign}/vods`, { url: job.label.replace(/^Analyse de /, "") }),
    onSuccess: () => toast.success("Analyse relancée : les étapes déjà faites sont réutilisées"),
    onError: (e) => toast.error(e.message),
  });
  const canRetry = job.kind === "process" || !!onRetry;
  const technical = job.logs.filter((l) => !l.startsWith("Traceback")).slice(-2).join("\n");
  const updateCmd = "uv lock --upgrade-package yt-dlp && uv sync";
  return (
    <div className="card-qc mb-10 border-pink/40 p-8">
      <p className="eyebrow mb-5">Erreur récupérable</p>
      <span className="mb-5 grid size-14 place-items-center rounded-2xl bg-pink-soft text-pink"><CircleAlert className="size-7" /></span>
      <h2 className="title-lg mb-3">{title(job)}</h2>
      <p className="mb-5 text-muted-foreground">
        {job.error} {job.kind === "process" && "Ce qui a déjà été téléchargé ou calculé est conservé : rien n'est perdu."}
      </p>
      {technical && <pre className="mb-6 overflow-x-auto rounded-2xl bg-secondary p-4 font-mono text-sm whitespace-pre-wrap text-muted-foreground">{technical}</pre>}
      {canRetry && (
        <button type="button" disabled={retry.isPending} onClick={() => (onRetry ? onRetry() : retry.mutate())}
                className="mb-3 h-12 w-full rounded-2xl bg-yellow font-semibold disabled:opacity-60">
          Réessayer
        </button>
      )}
      <div className="grid grid-cols-2 gap-3">
        <button type="button" className="flex h-12 items-center justify-center gap-2 rounded-2xl border border-line bg-secondary font-medium"
                onClick={() => navigator.clipboard.writeText(updateCmd).then(() => toast.success(`Commande copiée : ${updateCmd}`))}>
          <Copy className="size-4" /> Mettre yt-dlp à jour
        </button>
        <button type="button" disabled title="Import d'un fichier local : prévu dans un jalon suivant"
                className="h-12 rounded-2xl border border-line bg-secondary font-medium opacity-50">
          Importer un fichier
        </button>
      </div>
    </div>
  );
}

function title(job: Job) {
  if (/403|forbidden/i.test(job.error)) return "Téléchargement bloqué par la plateforme";
  if (/injoignable|connection|timed out/i.test(job.error)) return "Connexion impossible";
  return job.kind === "render" ? "Le rendu a échoué" : "L'analyse s'est arrêtée";
}

/** L'API ne répond pas : la seule action utile est de la lancer. */
export function ApiDown({ message }: { message: string }) {
  return (
    <div className="card-qc border-pink/40 p-8">
      <p className="eyebrow mb-5">API injoignable</p>
      <h2 className="title-lg mb-3">qClip ne répond pas</h2>
      <p className="mb-5 text-muted-foreground">{message}</p>
      <pre className="rounded-2xl bg-secondary p-4 font-mono text-sm">cd C:\Dev\qClip{"\n"}uv run qclip serve</pre>
    </div>
  );
}
