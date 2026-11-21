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

/** Brief de campagne tel que renvoyé par l'API (mêmes champs que qclip/campaign.py). */
export type Brief = {
  name: string;
  creator: string;
  platforms: ("tiktok" | "shorts" | "reels")[];
  rate_per_1k: number;
  sources: string[];
  clip: { min_len: number; max_len: number };
  required: { mention: string; hashtags: string[]; caption_note: string };
  forbidden: string[];
  layout: "facecam" | "blur" | "crop";
  language: string;
  test_only: boolean;
  facecam: number[] | null;
  brief_url: string;
  source_platform: "kick" | "twitch" | "youtube" | null;
  channel: string;
  source_rule: string;
  budget_total: number | null;
  payout_min: number | null;
  payout_max: number | null;
  overlay: { file: string; x: number; y: number; width: number; url?: string | null } | null;
  requirements: {
    link_in_bio: string;
    dedicated_account: boolean;
    linked_description: boolean;
    submit_within_min: number | null;
  };
  audience: { country: string; min_country_pct: number | null; min_engagement_pct: number | null };
};

export type BriefView = {
  slug: string;
  brief: Brief;
  checklist: { label: string; detail: string }[];
  summary?: CampaignSummary;
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

export type VodStep = { name: string; seconds: number };

export type VodStage = {
  key: "repérage" | "téléchargement" | "séparation" | "transcription" | "détection";
  name: string;
  state: "done" | "running" | "waiting";
  seconds?: number; // durée mesurée (absente si l'étape n'a pas encore été chronométrée)
  steps?: VodStep[]; // sous-étapes du repérage
  done?: number;
  total?: number;
  estimate_s?: number; // temps restant estimé d'après les VOD déjà traitées sur cette machine
};

export type VodWindow = {
  rank: number;
  start: number;
  end: number;
  peak: number;
  state: "waiting" | "fetched" | "audio" | "transcribed";
};

/** Écran VOD (maquette 3) : qclip/overview.py · vod_overview. */
export type Vod = {
  video_id: string;
  campaign: string;
  campaign_name: string;
  creator: string;
  title: string;
  url: string;
  platform: "kick" | "twitch" | "youtube" | null;
  language: string;
  duration: number;
  chat_messages: number;
  source_rule: string;
  radar: { chat: number[]; audio: number[] };
  windows: VodWindow[];
  stages: VodStage[];
  candidates: number;
  ready_windows: number;
  zones_seconds: number;
};

export type VodItem = { video_id: string; title: string; campaign: string; duration: number; updated: number };

/** Moment à trier (qclip/overview.py · moments). Temps en secondes de la VOD ; temps dans le fichier = t - window_start. */
export type Moment = {
  window: number;
  id: number;
  start: number;
  end: number;
  duration: number;
  peak: number;
  score: number; // signaux, ramenés sur 10 (le meilleur moment = 10)
  llm_score: number | null;
  reasons: string[];
  text: string;
  hook: string;
  title: string;
  decision: "keep" | "reject" | "skip" | null;
  video: string;
  window_start: number;
  window_duration: number | null;
  edited: boolean;
};

export type Moments = {
  video_id: string;
  moments: Moment[];
  kept: number;
  rejected: number;
  remaining: number;
  title: string;
  campaign: string;
  campaign_name: string;
  min_len: number;
  max_len: number;
};

export type Peaks = { duration: number; peaks: number[] };
