import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const fetchMock = vi.hoisted(() => vi.fn());
const tMock = vi.hoisted(() => (
  key: string,
  params?: Record<string, string | number>
) => {
  const labels: Record<string, string> = {
    'aiAssistant.audienceQuestion': 'Who is this course for?',
    'aiAssistant.primary': 'Priority audience',
    'aiAssistant.secondary': 'Additional audience',
    'aiAssistant.matched': `Matching employees: ${params?.count ?? '{count}'}`,
    'aiAssistant.alreadyAssigned': `Already assigned: ${params?.count ?? '{count}'}`,
    'aiAssistant.published': 'Course published',
    'aiAssistant.notPublished': 'Course not published yet',
    'aiAssistant.reviewHint': 'Assignment is completed after publication.',
    'aiAssistant.openAssignments': 'Go to assignments',
    'aiAssistant.organization': 'Whole organization',
    'aiAssistant.department': 'Department',
    'aiAssistant.position': 'Position',
    'aiAssistant.cohort': 'Group',
    'aiAssistant.confidence.high': 'High confidence',
    'aiAssistant.confidence.medium': 'Medium confidence',
    'aiAssistant.confidence.low': 'Low confidence',
    'common.close': 'Close',
  };
  return labels[key] ?? key;
});

vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (state: { accessToken: string }) => unknown) => selector({ accessToken: 'test-token' }),
}));

vi.mock('@/i18n/useT', () => ({
  useT: () => ({
    lang: 'en',
    t: tMock,
  }),
}));

vi.mock('@/components/ui/Toast', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import { AIChatPanel } from '@/components/ai/AIChatPanel';

function response(recommendation: unknown) {
  return new Response(JSON.stringify({ reply: 'Reviewed audience.', audience_recommendation: recommendation }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('AI audience recommendation card', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.example.test');
    vi.stubGlobal('fetch', fetchMock);
  });

  it('sends explicit audience intent and exposes only a published assignment link', async () => {
    fetchMock.mockResolvedValue(response({
      course_status: 'published',
      recommended_scopes: [{
        type: 'position', id: 'position-1', name: 'IT specialist', employee_count: 3,
        priority: 'primary', confidence: 'high', reasons: ['Explicit position rule'],
      }],
      matched_employee_count: 3,
      already_enrolled_count: 1,
      data_warnings: [],
      assignment_url: '/assignments?course_id=course-1',
    }));

    render(<AIChatPanel open onClose={vi.fn()} courseId="course-1" />);
    fireEvent.click(screen.getByRole('button', { name: 'Who is this course for?' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const request = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(request.intent).toBe('audience_recommendation');
    expect(request.course_id).toBe('course-1');
    expect(await screen.findByTestId('audience-recommendation')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to assignments' })).toHaveAttribute('href', '/assignments?course_id=course-1');
    expect(screen.queryByRole('button', { name: /assign/i })).not.toBeInTheDocument();
  });

  it('keeps draft recommendations read-only and hides assignment navigation', async () => {
    fetchMock.mockResolvedValue(response({
      course_status: 'draft',
      recommended_scopes: [],
      matched_employee_count: 0,
      already_enrolled_count: 0,
      data_warnings: ['Missing explicit structure links'],
      assignment_url: null,
    }));

    render(<AIChatPanel open onClose={vi.fn()} courseId="course-1" />);
    fireEvent.click(screen.getByRole('button', { name: 'Who is this course for?' }));

    await waitFor(() => expect(screen.getByTestId('audience-recommendation')).toBeInTheDocument());
    expect(screen.queryByRole('link', { name: 'Go to assignments' })).not.toBeInTheDocument();
    expect(screen.getByText('Assignment is completed after publication.')).toBeInTheDocument();
  });

  it('uses course context for the audience quick action even when the panel is lesson-focused', async () => {
    fetchMock.mockResolvedValue(response({
      course_status: 'draft',
      recommended_scopes: [],
      matched_employee_count: 0,
      already_enrolled_count: 0,
      data_warnings: [],
      assignment_url: null,
    }));

    render(
      <AIChatPanel
        open
        onClose={vi.fn()}
        courseId="course-1"
        focusLessonId="lesson-1"
        focusLessonTitle="Contact handling"
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Who is this course for?' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const request = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(request.intent).toBe('audience_recommendation');
    expect(request.context).toBe('course');
    expect(request.target_id).toBeNull();
  });
});
