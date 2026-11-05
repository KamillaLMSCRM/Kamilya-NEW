import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { FileText, Save } from 'lucide-react';
import { CoursePreviewTree, type CoursePreviewProps } from '@/app/ai/generate/components/CoursePreview';
import { GenerationProgressPanel } from '@/features/ai-generation/GenerationProgressPanel';
import { CourseReadiness } from '@/features/course-authoring/CourseReadiness';
import type { AIGenerationJob } from '@/lib/aiGenerationJobs';

vi.mock('@/i18n/useT', () => ({ useT: () => ({ t: (key: string) => key, lang: 'en' }) }));
afterEach(cleanup);

function previewProps(): CoursePreviewProps {
  return {
    modules: [{ id: 'module-owned', title: 'Source-based module', lessons: [{
      id: 'lesson-owned', title: 'Source-based lesson', content_preview: 'A retained lesson excerpt.',
      source_validation_status: 'needs_review',
      source_references: [{ doc_id: 'source-owned', doc_name: 'Safety procedure v3', headings: ['Section 4'] }],
    }] }],
    busyTargetId: null, editingLessonId: null, editForm: { title: '', content: '' }, editSaving: false,
    onRegenerateModule: vi.fn(), onRegenerateLesson: vi.fn(), onFocusChat: vi.fn(), onEditLesson: vi.fn(),
    onCancelEdit: vi.fn(), onSaveEdit: vi.fn(), onEditFormChange: vi.fn(),
  };
}

const labels = { queued: 'Queued', running: 'Running', completed: 'Completed', failed: 'Failed', cancelled: 'Cancelled', interrupted: 'Interrupted', stalled: 'Stalled' };
function progressProps(status: string) {
  const job: AIGenerationJob = {
    id: 'job-owned', status, course_id: status === 'interrupted' ? 'draft-owned' : null,
    stage: 'ingestion', progress: 25, created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    message: '', queue_position: null, estimated_wait_seconds: null, tenant_active_jobs: null, tenant_active_limit: null,
  };
  return {
    job, stages: [{ key: 'ingestion', label: 'Read sources', icon: FileText, color: 'text-primary' }, { key: 'saving', label: 'Save draft', icon: Save, color: 'text-primary' }],
    title: 'Generation', labels, retryLabel: 'Continue job', checkAgainLabel: 'Check again', cancelLabel: 'Cancel job', cancelQueuedLabel: 'Cancel queued job',
    queueTitle: 'Queue', activeJobs: 'Active jobs', queuePosition: 'Queue position', estimatedWait: 'Estimated wait', queueEstimateHint: 'An estimate only', completedUnitsLabel: 'Saved lessons',
    onRetry: vi.fn(), onCancel: vi.fn(), lang: 'en',
  };
}

describe('authoring screen-owned presentation neighbours', () => {
  it('keeps a legible module action group and exact module/lesson callback ownership', () => {
    const props = previewProps();
    render(<CoursePreviewTree {...props} />);
    const moduleAction = screen.getByRole('button', { name: 'authenticatedUi.coursePreview.askAi' });
    expect(moduleAction.parentElement).toHaveClass('flex-wrap');
    fireEvent.click(moduleAction);
    expect(props.onFocusChat).toHaveBeenCalledWith('module', 'module-owned');
    fireEvent.click(screen.getByRole('button', { name: /Source-based module/ }));
    fireEvent.click(screen.getByRole('button', { name: 'common.edit' }));
    expect(props.onEditLesson).toHaveBeenCalledWith('lesson-owned');
    fireEvent.click(screen.getByRole('button', { name: 'AI' }));
    expect(props.onFocusChat).toHaveBeenLastCalledWith('lesson', 'lesson-owned');
    const regenerate = screen.getAllByRole('button', { name: 'authenticatedUi.coursePreview.regenerate' });
    fireEvent.click(regenerate[1]);
    expect(props.onRegenerateLesson).toHaveBeenCalledWith('lesson-owned', 'Source-based lesson');
  });

  it('retains the source disclosure and neutral review warning beneath the lesson excerpt', () => {
    render(<CoursePreviewTree {...previewProps()} />);
    fireEvent.click(screen.getByRole('button', { name: /Source-based module/ }));
    const source = screen.getByText('Safety procedure v3');
    const disclosure = source.closest('details');
    expect(disclosure).not.toBeNull();
    fireEvent.click(within(disclosure!).getByText(/authenticatedUi.coursePreview.lessonSources/));
    expect(disclosure).toHaveAttribute('open');
    expect(screen.getByText('A retained lesson excerpt.')).toHaveClass('text-sm', 'leading-6');
    expect(screen.getByText('authenticatedUi.coursePreview.sourceReviewWarning')).toBeInTheDocument();
  });

  it('preserves edit controls and busy fences in the expanded outline', () => {
    const props = previewProps();
    render(<CoursePreviewTree {...props} busyTargetId="module-owned" />);
    fireEvent.click(screen.getByRole('button', { name: /Source-based module/ }));
    expect(screen.getByRole('button', { name: 'common.edit' })).toBeDisabled();
    expect(screen.getAllByRole('button', { name: 'authenticatedUi.coursePreview.regenerate' }).every((button) => button.hasAttribute('disabled'))).toBe(true);
  });

  it('separates real operation status from the stage paper without inventing queue fields', () => {
    const props = progressProps('pending');
    const { container } = render(<GenerationProgressPanel {...props} />);
    expect(screen.getByText('Queue')).toBeInTheDocument();
    expect(screen.queryByText('Queue position')).not.toBeInTheDocument();
    expect(screen.queryByText('Estimated wait')).not.toBeInTheDocument();
    const stage = container.querySelector('[aria-current="step"]');
    expect(stage).toHaveTextContent('Read sources');
    expect(stage?.closest('[data-workspace-panel]')).not.toContainElement(screen.getByRole('button', { name: 'Cancel queued job' }));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel queued job' }));
    expect(props.onCancel).toHaveBeenCalledOnce();
  });

  it('keeps interrupted draft navigation and existing retry/cancel commands available', () => {
    const props = progressProps('interrupted');
    render(<GenerationProgressPanel {...props} />);
    expect(screen.getByRole('link')).toHaveAttribute('href', '/courses/draft-owned/edit');
    fireEvent.click(screen.getByRole('button', { name: 'Continue job' }));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel job' }));
    expect(props.onRetry).toHaveBeenCalledOnce();
    expect(props.onCancel).toHaveBeenCalledOnce();
  });

  it.each(['ru', 'kk', 'en'])('groups factual readiness in paper for %s without a quality score', (lang) => {
    const { container } = render(<CourseReadiness lang={lang} moduleCount={2} lessonCount={4} dirty requiresReview reviewStatus="approved" unavailable />);
    const panel = container.querySelector('[data-workspace-panel]');
    expect(panel).toContainElement(screen.getByRole('heading', { level: 2 }));
    expect(panel?.querySelectorAll('dl > div')).toHaveLength(3);
    expect(container.textContent).not.toContain('100%');
    expect(container.textContent).not.toContain('2 ·');
  });
});
