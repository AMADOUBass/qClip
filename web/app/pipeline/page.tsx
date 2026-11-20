import { PageHeader } from "@/components/page-header";
import { Upcoming } from "@/components/upcoming";

export default function Page() {
  return (
    <>
      <PageHeader eyebrow="TOUS LES CLIPS" title="Pipeline" />
      <Upcoming screen="Pipeline des clips" step={7} />
    </>
  );
}
