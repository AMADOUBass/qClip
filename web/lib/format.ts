// Formats français des maquettes : « 48,20 $ », « 61,8 k », « 2:14:07 », « ≈ 19 min ».

const nf = (digits: number) =>
  new Intl.NumberFormat("fr-FR", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export const money = (value: number) => `${nf(2).format(value)} $`;

export const compact = (value: number) => {
  if (value >= 1_000_000) return `${nf(1).format(value / 1_000_000)} M`;
  if (value >= 1_000) return `${nf(1).format(value / 1_000)} k`;
  return String(value);
};

/** 8411 → « 2:20:11 » ; 41 → « 0:41 ». */
export const clock = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`;
};

/** Temps restant arrondi façon maquette : « ≈ 19 min », « ≈ 40 s ». */
export const eta = (seconds: number | null | undefined) => {
  if (seconds == null) return "";
  if (seconds < 60) return `≈ ${Math.max(1, Math.round(seconds))} s`;
  return `≈ ${Math.round(seconds / 60)} min`;
};

export const greeting = (date = new Date()) => {
  const h = date.getHours();
  return h < 5 || h >= 18 ? "Bonsoir" : "Bonjour";
};

/** Durée d'une étape façon maquette : « 6 min 08 », « 41 s », « 1 h 05 ». */
export const span = (seconds: number) => {
  const s = Math.round(seconds);
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")}`;
  return `${Math.floor(s / 3600)} h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}`;
};

/** Longueur d'une VOD : « 6 h 12 », « 30 min ». */
export const hm = (seconds: number) => {
  const m = Math.round(seconds / 60);
  return m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}` : `${m} min`;
};
