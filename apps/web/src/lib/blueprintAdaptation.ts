export interface AdaptationChecklistItem {
  id: string;
  required: boolean;
}

export interface AdaptationStep {
  id: string;
  titleKey: string;
  descriptionKey: string;
  itemIds: readonly string[];
}

const legacyFinanceChecklistIds = [
  'access_and_offboarding',
  'approved_systems',
  'data_classification',
  'remote_work',
  'removable_media',
  'fraud_verification',
  'incident_channel',
  'branch_specifics',
] as const;

export const adaptationSteps: readonly AdaptationStep[] = [
  {
    id: 'access',
    titleKey: 'courses.blueprint.steps.accessTitle',
    descriptionKey: 'courses.blueprint.steps.accessDescription',
    itemIds: legacyFinanceChecklistIds.slice(0, 3),
  },
  {
    id: 'operations',
    titleKey: 'courses.blueprint.steps.operationsTitle',
    descriptionKey: 'courses.blueprint.steps.operationsDescription',
    itemIds: legacyFinanceChecklistIds.slice(3, 6),
  },
  {
    id: 'incidents',
    titleKey: 'courses.blueprint.steps.incidentsTitle',
    descriptionKey: 'courses.blueprint.steps.incidentsDescription',
    itemIds: legacyFinanceChecklistIds.slice(6),
  },
];

export function buildAdaptationSteps(
  checklist: readonly AdaptationChecklistItem[],
): readonly AdaptationStep[] {
  const checklistIds = checklist.map((item) => item.id);
  if (
    checklistIds.length === legacyFinanceChecklistIds.length
    && legacyFinanceChecklistIds.every((id) => checklistIds.includes(id))
  ) {
    return adaptationSteps;
  }
  return [{
    id: 'checklist',
    titleKey: 'courses.blueprint.steps.checklistTitle',
    descriptionKey: 'courses.blueprint.steps.checklistDescription',
    itemIds: checklist.map((item) => item.id),
  }];
}

export function firstMissingAnswer(
  step: AdaptationStep,
  checklist: readonly AdaptationChecklistItem[],
  answers: Record<string, string>,
): string | undefined {
  const requiredIds = new Set(checklist.filter((item) => item.required).map((item) => item.id));
  return step.itemIds.find((itemId) => requiredIds.has(itemId) && !answers[itemId]?.trim());
}

export function completedAnswerCount(
  checklist: readonly AdaptationChecklistItem[],
  answers: Record<string, string>,
): number {
  return checklist.filter((item) => item.required && Boolean(answers[item.id]?.trim())).length;
}

export function firstIncompleteStep(
  checklist: readonly AdaptationChecklistItem[],
  answers: Record<string, string>,
): number {
  return buildAdaptationSteps(checklist).findIndex((step) => Boolean(firstMissingAnswer(step, checklist, answers)));
}

export function adaptationResumeStep(
  checklist: readonly AdaptationChecklistItem[],
  answers: Record<string, string>,
): number {
  const incompleteStep = firstIncompleteStep(checklist, answers);
  return incompleteStep === -1 ? buildAdaptationSteps(checklist).length - 1 : incompleteStep;
}
