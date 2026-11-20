import { PageHeader } from "@/components/page-header";
import { Upcoming } from "@/components/upcoming";

export default function Page() {
  return (
    <>
      <PageHeader eyebrow="ÉDITEUR" title="Éditeur de clip" />
      <Upcoming screen="Éditeur de clip" step={6} />
    </>
  );
}
