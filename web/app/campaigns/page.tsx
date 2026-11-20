import { PageHeader } from "@/components/page-header";
import { Upcoming } from "@/components/upcoming";

export default function Page() {
  return (
    <>
      <PageHeader eyebrow="CAMPAGNES" title="Campagnes" />
      <Upcoming screen="Campagnes et brief" step={3} />
    </>
  );
}
