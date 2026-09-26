import type { TranslationKey } from '@/i18n/useT';

export interface AssignmentSourceInfo {
  labelKey: TranslationKey;
  descriptionKey: TranslationKey;
  managedByRule: boolean;
}

const sourceInfo: Record<string, AssignmentSourceInfo> = {
  manual: {
    labelKey: 'assignmentSources.manual.label',
    descriptionKey: 'assignmentSources.manual.description',
    managedByRule: false,
  },
  position: {
    labelKey: 'assignmentSources.position.label',
    descriptionKey: 'assignmentSources.position.description',
    managedByRule: true,
  },
  department: {
    labelKey: 'assignmentSources.department.label',
    descriptionKey: 'assignmentSources.department.description',
    managedByRule: true,
  },
  organization: {
    labelKey: 'assignmentSources.organization.label',
    descriptionKey: 'assignmentSources.organization.description',
    managedByRule: true,
  },
  cohort: {
    labelKey: 'assignmentSources.cohort.label',
    descriptionKey: 'assignmentSources.cohort.description',
    managedByRule: true,
  },
  learning_path: {
    labelKey: 'assignmentSources.learningPath.label',
    descriptionKey: 'assignmentSources.learningPath.description',
    managedByRule: true,
  },
  recurring: {
    labelKey: 'assignmentSources.recurring.label',
    descriptionKey: 'assignmentSources.recurring.description',
    managedByRule: true,
  },
  auto: {
    labelKey: 'assignmentSources.auto.label',
    descriptionKey: 'assignmentSources.auto.description',
    managedByRule: true,
  },
};

const unknownSource: AssignmentSourceInfo = {
  labelKey: 'assignmentSources.unknown.label',
  descriptionKey: 'assignmentSources.unknown.description',
  managedByRule: true,
};

export const getAssignmentSourceInfo = (source: string): AssignmentSourceInfo =>
  sourceInfo[source] || unknownSource;
