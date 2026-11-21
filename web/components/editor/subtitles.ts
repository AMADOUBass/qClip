// Même découpage et mêmes temps que qclip/subtitles.py (build_ass, group_lines) : l'aperçu affiche à chaque instant
// la ligne et le mot que le rendu brûlera. Temps en secondes depuis le début du clip.

import type { EditorWord } from "@/lib/api";

export type Line = { words: EditorWord[]; start: number; end: number };

/** group_lines : au plus `perLine` mots, coupure en fin de phrase, sur une virgule (ligne ≥ 2 mots) ou avant une pause. */
export function groupLines(words: EditorWord[], perLine: number, gap: number): EditorWord[][] {
  const lines: EditorWord[][] = [];
  let current: EditorWord[] = [];
  for (const w of words) {
    if (current.length && (current.length >= perLine || w.start - current[current.length - 1].end >= gap)) {
      lines.push(current);
      current = [];
    }
    current.push(w);
    const text = w.text.trimEnd();
    if (/[.?!…]$/.test(text) || (text.endsWith(",") && current.length >= 2)) {
      lines.push(current);
      current = [];
    }
  }
  if (current.length) lines.push(current);
  return lines;
}

/** Lignes avec leur fenêtre d'affichage : du premier mot jusqu'à min(dernier mot + hold, ligne suivante, fin du clip). */
export function timedLines(words: EditorWord[], perLine: number, gap: number, hold: number, duration: number): Line[] {
  const groups = groupLines(words, perLine, gap);
  return groups.map((line, n) => {
    const next = n + 1 < groups.length ? groups[n + 1][0].start : duration;
    return { words: line, start: line[0].start, end: Math.min(line[line.length - 1].end + hold, next, duration) };
  });
}

/** Ligne affichée à l'instant t et index du mot surligné (comme les évènements ASS mot par mot). */
export function activeAt(lines: Line[], t: number): { line: Line; word: number } | null {
  const line = lines.find((l) => t >= l.start && t < l.end);
  if (!line) return null;
  let word = 0;
  line.words.forEach((w, i) => {
    if (i > 0 && t >= w.start) word = i;
  });
  return { line, word };
}
