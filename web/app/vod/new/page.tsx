import { PageHeader } from "@/components/page-header";
import { Upcoming } from "@/components/upcoming";

export default function Page() {
  return (
    <>
      <PageHeader eyebrow="VOD / NOUVELLE" title="Nouvelle VOD" />
      <Upcoming screen="Ajout d'une VOD" step={4} />
    </>
  );
}
