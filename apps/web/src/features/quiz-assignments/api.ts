/**
 * Quiz Assignments API client.
 *
 * Endpoints (see `apps/api/app/modules/quizzes/assignment_router.py`):
 *   GET    /v1/quiz-assignments                — list all assignments in tenant
 *   POST   /v1/quiz-assignments                — bulk assign { quiz_id, user_ids[], due_date }
 *   POST   /v1/quiz-assignments/by-positions   — assign via positions (expands to user_ids)
 *   DELETE /v1/quiz-assignments/{id}           — remove one assignment
 *
 * We do NOT use the cached "my" endpoint — methodologists always look at
 * the full list to see who has / hasn't completed a quiz.
 */
import type {
  AssignmentCreateResult,
  PositionAssignmentSummary,
  QuizAssignment,
} from './types';

const BASE = (process.env.NEXT_PUBLIC_API_URL ?? '').replace(/\/$/, '');

export interface AssignQuizRequest {
  quiz_id: string;
  user_ids: string[];
  due_date?: string | null;
}

export interface AssignByPositionsRequest {
  quiz_id: string;
  position_ids: string[];
  due_date?: string | null;
}

async function authHeader(token: string): Promise<HeadersInit> {
  return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
}

export async function fetchAssignments(token: string): Promise<QuizAssignment[]> {
  const res = await fetch(`${BASE}/v1/quiz-assignments`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(detail.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function assignQuiz(
  token: string,
  req: AssignQuizRequest
): Promise<AssignmentCreateResult> {
  const res = await fetch(`${BASE}/v1/quiz-assignments`, {
    method: 'POST',
    headers: await authHeader(token),
    body: JSON.stringify({
      quiz_id: req.quiz_id,
      user_ids: req.user_ids,
      due_date: req.due_date ?? null,
    }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(detail.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function assignQuizByPositions(
  token: string,
  req: AssignByPositionsRequest
): Promise<PositionAssignmentSummary> {
  const res = await fetch(`${BASE}/v1/quiz-assignments/by-positions`, {
    method: 'POST',
    headers: await authHeader(token),
    body: JSON.stringify({
      quiz_id: req.quiz_id,
      position_ids: req.position_ids,
      due_date: req.due_date ?? null,
    }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(detail.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function removeAssignment(token: string, assignmentId: string): Promise<void> {
  const res = await fetch(`${BASE}/v1/quiz-assignments/${assignmentId}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(detail.detail || `HTTP ${res.status}`);
  }
}