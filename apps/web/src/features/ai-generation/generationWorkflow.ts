import type { AIGenerationJob } from '@/lib/aiGenerationJobs';

export type GenerationRouteStep = 'documents' | 'generate' | 'review';

export interface GenerationWorkflowState {
  currentJob: AIGenerationJob | null;
  step: GenerationRouteStep;
  programId: string | null;
}

export type GenerationWorkflowAction =
  | { type: 'job_started'; job: AIGenerationJob; programId?: string | null }
  | { type: 'job_restored'; job: AIGenerationJob; programId: string | null }
  | { type: 'job_active'; job: AIGenerationJob }
  | { type: 'job_completed'; job: AIGenerationJob }
  | { type: 'job_terminal'; job: AIGenerationJob }
  | { type: 'job_cleared' };

export const initialGenerationWorkflowState: GenerationWorkflowState = {
  currentJob: null,
  step: 'documents',
  programId: null,
};

export function generationWorkflowReducer(
  state: GenerationWorkflowState,
  action: GenerationWorkflowAction,
): GenerationWorkflowState {
  switch (action.type) {
    case 'job_started':
    case 'job_restored':
      return { currentJob: action.job, step: action.job.status === 'completed' ? 'review' : 'generate', programId: action.programId ?? null };
    case 'job_active':
      return { ...state, currentJob: action.job, step: 'generate' };
    case 'job_completed':
      return { ...state, currentJob: action.job, step: 'review' };
    case 'job_terminal':
      return { ...state, currentJob: action.job, step: 'generate' };
    case 'job_cleared':
      return { ...initialGenerationWorkflowState, programId: state.programId };
    default:
      return state;
  }
}
