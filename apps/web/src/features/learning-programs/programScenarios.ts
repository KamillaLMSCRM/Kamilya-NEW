export type ProgramScenarioId =
  | 'onboarding'
  | 'mandatory_training'
  | 'process_update'
  | 'product_certification'
  | 'knowledge_refresh'
  | 'custom';

export type ProgramScenario = {
  id: ProgramScenarioId;
  titleKey: string;
  descriptionKey: string;
  guidanceKey: string;
  titlePlaceholderKey: string;
  descriptionPlaceholderKey: string;
};

export const PROGRAM_SCENARIOS: readonly ProgramScenario[] = [
  {
    id: 'onboarding',
    titleKey: 'learningPaths.scenario.onboarding.title',
    descriptionKey: 'learningPaths.scenario.onboarding.description',
    guidanceKey: 'learningPaths.scenario.onboarding.guidance',
    titlePlaceholderKey: 'learningPaths.scenario.onboarding.titlePlaceholder',
    descriptionPlaceholderKey: 'learningPaths.scenario.onboarding.descriptionPlaceholder',
  },
  {
    id: 'mandatory_training',
    titleKey: 'learningPaths.scenario.mandatoryTraining.title',
    descriptionKey: 'learningPaths.scenario.mandatoryTraining.description',
    guidanceKey: 'learningPaths.scenario.mandatoryTraining.guidance',
    titlePlaceholderKey: 'learningPaths.scenario.mandatoryTraining.titlePlaceholder',
    descriptionPlaceholderKey: 'learningPaths.scenario.mandatoryTraining.descriptionPlaceholder',
  },
  {
    id: 'process_update',
    titleKey: 'learningPaths.scenario.processUpdate.title',
    descriptionKey: 'learningPaths.scenario.processUpdate.description',
    guidanceKey: 'learningPaths.scenario.processUpdate.guidance',
    titlePlaceholderKey: 'learningPaths.scenario.processUpdate.titlePlaceholder',
    descriptionPlaceholderKey: 'learningPaths.scenario.processUpdate.descriptionPlaceholder',
  },
  {
    id: 'knowledge_refresh',
    titleKey: 'learningPaths.scenario.knowledgeRefresh.title',
    descriptionKey: 'learningPaths.scenario.knowledgeRefresh.description',
    guidanceKey: 'learningPaths.scenario.knowledgeRefresh.guidance',
    titlePlaceholderKey: 'learningPaths.scenario.knowledgeRefresh.titlePlaceholder',
    descriptionPlaceholderKey: 'learningPaths.scenario.knowledgeRefresh.descriptionPlaceholder',
  },
  {
    id: 'product_certification',
    titleKey: 'learningPaths.scenario.roleCertification.title',
    descriptionKey: 'learningPaths.scenario.roleCertification.description',
    guidanceKey: 'learningPaths.scenario.roleCertification.guidance',
    titlePlaceholderKey: 'learningPaths.scenario.roleCertification.titlePlaceholder',
    descriptionPlaceholderKey: 'learningPaths.scenario.roleCertification.descriptionPlaceholder',
  },
  {
    id: 'custom',
    titleKey: 'learningPaths.scenario.custom.title',
    descriptionKey: 'learningPaths.scenario.custom.description',
    guidanceKey: 'learningPaths.scenario.custom.guidance',
    titlePlaceholderKey: 'learningPaths.scenario.custom.titlePlaceholder',
    descriptionPlaceholderKey: 'learningPaths.scenario.custom.descriptionPlaceholder',
  },
];
