import { api } from '@/lib/api';
import type {
  MandatoryTrainingPage,
  MandatoryTrainingSummary,
  RequirementAction,
  RequirementState,
} from './types';

export interface MandatoryTrainingFilters {
  search?: string;
  requirement_state?: RequirementState;
  action_required?: RequirementAction;
  include_inactive?: boolean;
  limit?: number;
  offset?: number;
}

export async function loadMandatoryTraining(
  filters: MandatoryTrainingFilters,
  signal: AbortSignal,
): Promise<{ page: MandatoryTrainingPage; summary: MandatoryTrainingSummary }> {
  const pageParams = Object.fromEntries(
    Object.entries(filters).filter(([, value]) => value !== undefined && value !== '' && value !== false),
  );
  const { limit: _limit, offset: _offset, ...summaryParams } = pageParams;
  const [page, summary] = await Promise.all([
    api.get<MandatoryTrainingPage>('/v1/admin/mandatory-training', { params: pageParams, signal }),
    api.get<MandatoryTrainingSummary>('/v1/admin/mandatory-training/summary', { params: summaryParams, signal }),
  ]);
  return { page: page.data, summary: summary.data };
}
