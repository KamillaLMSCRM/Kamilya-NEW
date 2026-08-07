import type { AIGenerationJob } from '@/lib/aiGenerationJobs';

export type GenerationRouteStep = 'documents' | 'generate' | 'review';

export interface GenerationWorkflowState {
  currentJob: AIGenerationJob | null;
  step: GenerationRouteStep;
}

export type GenerationWorkflowAction =
  | { type: 'job_started'; job: AIGenerationJob }
  | { type: 'job_active'; job: AIGenerationJob }
  | { type: 'job_completed'; job: AIGenerationJob }
  | { type: 'job_terminal'; job: AIGenerationJob }
  | { type: 'job_cleared' };

export const initialGenerationWorkflowState: GenerationWorkflowState = {
  currentJob: null,
  step: 'documents',
};

export function generationWorkflowReducer(
  state: GenerationWorkflowState,
  action: GenerationWorkflowAction,
): GenerationWorkflowState {
  switch (action.type) {
    case 'job_started':
    case 'job_active':
      return { currentJob: action.job, step: 'generate' };
    case 'job_completed':
      return { currentJob: action.job, step: 'review' };
    case 'job_terminal':
      return { currentJob: action.job, step: 'generate' };
    case 'job_cleared':
      return initialGenerationWorkflowState;
    default:
      return state;
  }
}
