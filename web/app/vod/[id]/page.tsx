"use client";

import { useParams } from "next/navigation";

import { VodView } from "@/components/vod/vod-view";

export default function VodPage() {
  const { id } = useParams<{ id: string }>();
  return <VodView key={id} vid={id} />;
}
