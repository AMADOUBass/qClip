import { PageHeader } from "@/components/page-header";
import { Upcoming } from "@/components/upcoming";

export default function Page() {
  return (
    <>
      <PageHeader eyebrow="VOD" title="VOD" />
      <Upcoming screen="VOD — radar et traitement" step={4} />
    </>
  );
}
