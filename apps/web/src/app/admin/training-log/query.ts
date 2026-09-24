export interface TrainingLogFilters {
  enrollment_id?: string;
  course_id?: string;
  department_id?: string;
  position_id?: string;
  status?: 'assigned' | 'in_progress' | 'completed' | 'overdue';
  delivery_type?: 'native' | 'scorm';
  date_from?: string;
  date_to?: string;
  search?: string;
  history?: boolean;
}

export interface TrainingLogBrowserState {
  filters: TrainingLogFilters;
  search: string;
  returnTo: '/dashboard' | null;
}

const FILTER_KEYS = [
  'enrollment_id',
  'course_id',
  'department_id',
  'position_id',
  'status',
  'delivery_type',
  'date_from',
  'date_to',
  'history',
] as const;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const STATUS_VALUES = new Set(['assigned', 'in_progress', 'completed', 'overdue']);
const DELIVERY_VALUES = new Set(['native', 'scorm']);

function validDate(value: string | null): value is string {
  return Boolean(value && value.length <= 40 && !Number.isNaN(Date.parse(value)));
}

function validUuid(value: string | null): value is string {
  return Boolean(value && UUID_PATTERN.test(value));
}

export function parseTrainingLogBrowserQuery(
  params: Pick<URLSearchParams, 'get'>,
): TrainingLogBrowserState {
  const filters: TrainingLogFilters = {};

  const enrollmentId = params.get('enrollment_id');
  const courseId = params.get('course_id');
  const departmentId = params.get('department_id');
  const positionId = params.get('position_id');
  const status = params.get('status');
  const deliveryType = params.get('delivery_type');
  const dateFrom = params.get('date_from');
  const dateTo = params.get('date_to');

  if (validUuid(enrollmentId)) filters.enrollment_id = enrollmentId;
  if (validUuid(courseId)) filters.course_id = courseId;
  if (validUuid(departmentId)) filters.department_id = departmentId;
  if (validUuid(positionId)) filters.position_id = positionId;
  if (status && STATUS_VALUES.has(status)) filters.status = status as TrainingLogFilters['status'];
  if (deliveryType && DELIVERY_VALUES.has(deliveryType)) filters.delivery_type = deliveryType as TrainingLogFilters['delivery_type'];
  if (validDate(dateFrom)) filters.date_from = dateFrom;
  if (validDate(dateTo)) filters.date_to = dateTo;
  if (params.get('history') === 'true') filters.history = true;

  const rawSearch = params.get('search');
  const search = rawSearch?.trim() ?? '';
  const returnTo = params.get('return_to') === '/dashboard' ? '/dashboard' : null;

  return {
    filters,
    search: search.length <= 200 ? search : '',
    returnTo,
  };
}

/** Build the shared, non-paginated filter portion for table, summary, and CSV. */
export function buildTrainingLogFilterQuery(
  filters: TrainingLogFilters,
  searchInput: string,
): URLSearchParams {
  const params = new URLSearchParams();
  FILTER_KEYS.forEach((key) => {
    const value = filters[key];
    if (value) params.set(key, String(value));
  });

  const search = searchInput.trim();
  if (search) params.set('search', search);
  return params;
}

export function buildTrainingLogBrowserHref(state: TrainingLogBrowserState): string {
  const params = buildTrainingLogFilterQuery(state.filters, state.search);
  if (state.returnTo === '/dashboard') params.set('return_to', state.returnTo);
  const query = params.toString();
  return query ? `/training-log?${query}` : '/training-log';
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
