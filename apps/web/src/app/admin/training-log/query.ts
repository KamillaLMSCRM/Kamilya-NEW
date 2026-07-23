export interface TrainingLogFilters {
  course_id?: string;
  department_id?: string;
  position_id?: string;
  status?: 'assigned' | 'in_progress' | 'completed';
  delivery_type?: 'native' | 'scorm';
  date_from?: string;
  date_to?: string;
  search?: string;
}

/** Build the shared, non-paginated filter portion for table, summary, and CSV. */
export function buildTrainingLogFilterQuery(
  filters: TrainingLogFilters,
  searchInput: string,
): URLSearchParams {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, String(value));
  });

  const search = searchInput.trim();
  if (search) params.set('search', search);
  return params;
}

export function buildTrainingLogPageQuery(
  filters: TrainingLogFilters,
  searchInput: string,
  limit: number,
  offset: number,
): string {
  const params = buildTrainingLogFilterQuery(filters, searchInput);
  params.set('limit', String(limit));
  params.set('offset', String(offset));
  return params.toString();
}
