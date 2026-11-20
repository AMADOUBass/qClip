import { PageHeader } from "@/components/page-header";
import { Upcoming } from "@/components/upcoming";

export default function Page() {
  return (
    <>
      <PageHeader eyebrow="TRI" title="Tri des moments" />
      <Upcoming screen="Tri des moments" step={5} />
    </>
  );
}
