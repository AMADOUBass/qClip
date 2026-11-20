// Client de l'API locale qClip (`qclip serve`, http://127.0.0.1:8765). Aucune logique métier ici.

export const API = process.env.NEXT_PUBLIC_QCLIP_API ?? "http://127.0.0.1:8765";

/** URL d'un fichier servi par l'API (vidéos, miniatures, overlay) à partir d'un chemin « work/… ». */
export const media = (path: string) => `${API}/media/${path.split("/").map(encodeURIComponent).join("/")}`;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API}${path}`, {
      ...init,
      headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError("API injoignable : lance `uv run qclip serve` dans le dossier du projet.", 0);
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(data?.detail ?? `Erreur ${response.status}`, response.status);
  return data as T;
}

export const post = <T>(path: string, body: unknown) => api<T>(path, { method: "POST", body: JSON.stringify(body) });
export const put = <T>(path: string, body: unknown) => api<T>(path, { method: "PUT", body: JSON.stringify(body) });

// --- types renvoyés par qclip/overview.py et qclip/jobs.py -------------------------------------------

export type Job = {
  id: number;
  kind: "process" | "render" | "rerank" | "meta";
  label: string;
  campaign: string;
  video_id: string | null;
  status: "queued" | "running" | "done" | "error";
  stage: string;
  step: string;
  progress: [number, number] | null;
  eta_s: number | null;
  stage_times: Record<string, number>;
  logs: string[];
  error: string;
  elapsed_s: number;
};

export type SystemStatus = {
  cpu_percent: number;
  ram_used_gb: number;
  ram_total_gb: number;
  disk_free_gb: number;
  job: Job | null;
};

export type CampaignSummary = {
  slug: string;
  name: string;
  creator: string;
  initials: string;
  platform: "kick" | "twitch" | "youtube" | null;
  language: string;
  rate_per_1k: number;
  payout_min: number | null;
  payout_max: number | null;
  budget_total: number | null;
  budget_left: number | null;
  clips: number;
  posted: number;
  views: number;
  earnings: number;
  paid: number;
  test_only: boolean;
  warning: string | null;
  note: string | null;
  vods: string[];
};

export type PipelineItem = {
  campaign: string;
  campaign_name: string;
  creator: string;
  video_id: string;
  clip_id: number;
  title: string;
  hook: string;
  duration: number | null;
  status: "a_revoir" | "rendu" | "poste" | "paye";
  caption: string;
  thumbnail: string;
  video: string;
  views: number;
  estimate: number;
  paid: number;
  rendered_at: string;
  test_only: boolean;
};

export type Dashboard = {
  date: string;
  paid_7d: number;
  paid_series: number[];
  paid_today: number;
  paid_clips_7d: number;
  views: number;
  views_series: number[];
  to_sort: number;
  ready: number;
  to_check: number;
  campaigns: CampaignSummary[];
  recent_clips: PipelineItem[];
  job: Job | null;
};
