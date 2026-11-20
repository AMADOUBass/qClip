// Emplacement d'un écran dont la maquette sera branchée à une étape suivante de M8 (rien d'inventé ici).

export function Upcoming({ screen, step }: { screen: string; step: number }) {
  return (
    <div className="card-qc grid min-h-80 place-items-center p-10 text-center">
      <div>
        <p className="eyebrow mb-3">Étape {step} de M8</p>
        <p className="title-lg mb-2">{screen}</p>
        <p className="text-muted-foreground">Cet écran suit la maquette de docs/design/ ; il arrive à l&apos;étape {step}.</p>
      </div>
    </div>
  );
}
