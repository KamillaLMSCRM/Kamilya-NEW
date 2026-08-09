export interface AdaptationChecklistItem {
  id: string;
  required: boolean;
}

export interface AdaptationStep {
  id: 'access' | 'operations' | 'incidents';
  titleKey: string;
  descriptionKey: string;
  itemIds: readonly string[];
}

export const adaptationSteps: readonly AdaptationStep[] = [
  {
    id: 'access',
    titleKey: 'courses.blueprint.steps.accessTitle',
    descriptionKey: 'courses.blueprint.steps.accessDescription',
    itemIds: ['access_and_offboarding', 'approved_systems', 'data_classification'],
  },
  {
    id: 'operations',
    titleKey: 'courses.blueprint.steps.operationsTitle',
    descriptionKey: 'courses.blueprint.steps.operationsDescription',
    itemIds: ['remote_work', 'removable_media', 'fraud_verification'],
  },
  {
    id: 'incidents',
    titleKey: 'courses.blueprint.steps.incidentsTitle',
    descriptionKey: 'courses.blueprint.steps.incidentsDescription',
    itemIds: ['incident_channel', 'branch_specifics'],
  },
];

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
  return adaptationSteps.findIndex((step) => Boolean(firstMissingAnswer(step, checklist, answers)));
}

export function adaptationResumeStep(
  checklist: readonly AdaptationChecklistItem[],
  answers: Record<string, string>,
): number {
  const incompleteStep = firstIncompleteStep(checklist, answers);
  return incompleteStep === -1 ? adaptationSteps.length - 1 : incompleteStep;
}
