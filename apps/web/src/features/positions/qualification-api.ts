import { api } from "@/lib/api";

import type { PositionQualificationCardData, QualificationHistoryItem } from "./qualification-types";

export async function getQualificationCard(positionId: string) {
  const response = await api.get<PositionQualificationCardData>(`/v1/positions/${positionId}/qualification-card`);
  return response.data;
}

export async function updateQualificationProfile(
  positionId: string,
  payload: {
    name: string;
    department: string;
    level: string;
    responsibilities: string;
    requirements: string;
    change_reason?: string;
  },
) {
  const response = await api.patch<PositionQualificationCardData>(
    `/v1/positions/${positionId}/qualification-profile`,
    payload,
  );
  return response.data;
}

export async function replacePositionCompetencies(
  positionId: string,
  items: Array<{ competency_id: string; required_level: number }>,
  changeReason?: string,
) {
  const response = await api.put<PositionQualificationCardData>(
    `/v1/positions/${positionId}/qualification-competencies`,
    { items, change_reason: changeReason || undefined },
  );
  return response.data;
}

export async function replaceMandatoryTraining(
  positionId: string,
  items: Array<{ course_id: string; required: boolean }>,
  changeReason?: string,
) {
  const response = await api.put<PositionQualificationCardData>(`/v1/positions/${positionId}/mandatory-training`, {
    items,
    change_reason: changeReason || undefined,
  });
  return response.data;
}

export async function getQualificationHistory(positionId: string) {
  const response = await api.get<{ items: QualificationHistoryItem[] }>(
    `/v1/positions/${positionId}/qualification-history`,
  );
  return response.data.items;
}

export async function restoreQualificationVersion(positionId: string, versionId: string, changeReason?: string) {
  const response = await api.post<PositionQualificationCardData>(
    `/v1/positions/${positionId}/qualification-history/${versionId}/restore`,
    { change_reason: changeReason || undefined },
  );
  return response.data;
}
