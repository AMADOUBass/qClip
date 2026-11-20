// Petite courbe des cartes du tableau de bord (gains, vues). Rien d'affiché tant qu'il n'y a pas de données.

export function Sparkline({ values, className, color = "currentColor" }: {
  values: number[];
  className?: string;
  color?: string;
}) {
  if (values.length < 2 || values.every((v) => v === values[0])) {
    return <svg viewBox="0 0 160 40" className={className} aria-hidden><line x1="0" x2="160" y1="34" y2="34" stroke={color} strokeOpacity={0.25} strokeWidth={2} /></svg>;
  }
  const max = Math.max(...values);
  const min = Math.min(...values);
  const points = values
    .map((v, i) => `${(i / (values.length - 1)) * 160},${36 - ((v - min) / (max - min || 1)) * 32}`)
    .join(" ");
  return (
    <svg viewBox="0 0 160 40" className={className} aria-hidden>
      <polyline points={points} fill="none" stroke={color} strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
