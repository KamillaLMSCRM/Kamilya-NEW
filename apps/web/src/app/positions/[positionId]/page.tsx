"use client";

import { useParams } from "next/navigation";

import { PositionQualificationCard } from "@/features/positions/PositionQualificationCard";

export default function PositionQualificationPage() {
  const params = useParams<{ positionId: string }>();
  return <PositionQualificationCard positionId={params.positionId} />;
}
