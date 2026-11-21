import type { MatchingChoice } from '@/features/quiz/MatchingPairs';

export type Choice = { id: string; text: string; is_correct: boolean };
export type Question = { id: string; text: string; type: 'MCQ' | 'multiple_choice' | 'true_false' | 'ordering' | 'matching_pairs'; points: number; explanation: string; choices: Choice[] };
export type Content = { title: string; instructions: string; pass_score: number; attempt_limit: number; time_limit_minutes: number | null; questions: Question[] };
export type Check = Content & { id: string; revision: number; status: string };
export type Assignment = { id: string; check_id: string; title: string; revision: number; due_at: string | null; status: string; attempt_limit: number; attempts_count: number; score_percent: number | null; passed: boolean };
export type Answer = { question_id: string; selected_choice_ids: string[] };
export type PublicQuestion = { id: string; text: string; type: Question['type']; points: number; choices: MatchingChoice[] };
export type Attempt = { id: string; assignment_id: string; number: number; status: string; started_at: string; deadline_at: string | null; completed_at: string | null; score_percent: number | null; passed: boolean | null; earned_points: number | null; total_points: number | null; answers: Answer[]; snapshot: { title: string; instructions: string; questions: PublicQuestion[] } };
export const uuid = () => crypto.randomUUID();
export const newQuestion = (): Question => ({ id: uuid(), text: '', type: 'MCQ', points: 1, explanation: '', choices: [{ id: uuid(), text: '', is_correct: true }, { id: uuid(), text: '', is_correct: false }] });
export const newContent = (): Content => ({ title: '', instructions: '', pass_score: 70, attempt_limit: 1, time_limit_minutes: null, questions: [newQuestion()] });
