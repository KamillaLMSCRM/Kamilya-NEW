import { api } from '@/lib/api';
import type { CourseInsights, EnrollmentInsights, LearningInsightsFilters, Review, ReviewStatus } from './types';

const BASE = '/v1/admin/learning-insights';

function isDateOnly(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value);
}

export function encodeLearningInsightsDate(value: string, boundary: 'start' | 'end'): string {
  const trimmed = value.trim();
  if (!isDateOnly(trimmed)) return trimmed;
  return `${trimmed}T${boundary === 'start' ? '00:00:00' : '23:59:59.999999'}+05:00`;
}

export async function getCourseInsights(courseId: string, filters: LearningInsightsFilters): Promise<CourseInsights> {
  const params = new URLSearchParams();
  if (filters.departmentId) params.set('department_id', filters.departmentId);
  if (filters.positionId) params.set('position_id', filters.positionId);
  if (filters.dateFrom) params.set('date_from', encodeLearningInsightsDate(filters.dateFrom, 'start'));
  if (filters.dateTo) params.set('date_to', encodeLearningInsightsDate(filters.dateTo, 'end'));
  const response = await api.get<CourseInsights>(`${BASE}/courses/${courseId}${params.size ? `?${params}` : ''}`);
  return response.data;
}

export async function getEnrollmentInsights(enrollmentId: string): Promise<EnrollmentInsights> {
  const response = await api.get<EnrollmentInsights>(`${BASE}/enrollments/${enrollmentId}`);
  return response.data;
}

export async function saveQuestionReview(attemptId: string, questionId: string, status: ReviewStatus): Promise<Review> {
  const response = await api.put<Review>(`${BASE}/attempts/${attemptId}/questions/${questionId}/review`, { status });
  return response.data;
}
