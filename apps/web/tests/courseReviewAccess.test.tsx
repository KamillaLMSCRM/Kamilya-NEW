import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const replaceMock = vi.hoisted(() => vi.fn());
const verifyMock = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useParams: () => ({ token: 'scoped-token' }), useRouter: () => ({ replace: replaceMock }) }));
vi.mock('@/lib/courseApproval', () => ({ verifyReviewPin: verifyMock }));

import CourseReviewAccessPage from '@/app/course-review-access/[token]/page';

describe('scoped review access', () => {
  beforeEach(() => { sessionStorage.clear(); replaceMock.mockReset(); verifyMock.mockReset().mockResolvedValue({ review_token: 'review-jwt', work_item_id: 'work-item' }); });
  it('stores the scoped credential only in session scope and enters the public review shell', async () => {
    render(<CourseReviewAccessPage />);
    fireEvent.change(screen.getByLabelText('PIN'), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить доступ' }));
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith('/course-review-access/review'));
    expect(sessionStorage.getItem('course_review_token')).toBe('review-jwt');
    expect(localStorage.getItem('course_review_token')).toBeNull();
  });
  it('clears a stale scoped credential when PIN verification fails', async () => {
    sessionStorage.setItem('course_review_token', 'stale');
    verifyMock.mockRejectedValue(new Error('expired'));
    render(<CourseReviewAccessPage />);
    fireEvent.change(screen.getByLabelText('PIN'), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить доступ' }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(sessionStorage.getItem('course_review_token')).toBeNull();
  });
});
