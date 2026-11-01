import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DocumentInspection } from '@/features/learning-workspace/DocumentInspection';
import { GenerationProgressPanel } from '@/features/ai-generation/GenerationProgressPanel';
import type { DocumentCatalogItem } from '@/lib/documentCatalog';
import type { AIGenerationJob } from '@/lib/aiGenerationJobs';

const document: DocumentCatalogItem = {
  id: 'source-1', source_family_id: 'family-1', title: 'Source policy', filename: 'policy.pdf',
  content_type: 'application/pdf', size: 1024, description: '', category: 'general',
  index: { status: 'partial', error_code: null, message: 'Two fragments unavailable', chunks_total: 10, chunks_indexed: 8, indexed_at: null, revision: 2 },
  version: 3, is_latest: true, lifecycle_status: 'active', deletion_error_code: null,
  deletion_error_message: null, deletion_job_id: null, created_by: null, created_at: '', updated_at: '',
};

describe('honest source and generation recovery presentation', () => {
  it('displays real index metadata and unknown usage without pretending to expose extraction', () => {
    const download = vi.fn();
    const usages = vi.fn();
    render(<DocumentInspection document={document} lang="en" downloading={false} onClose={() => {}} onDownload={download} onUsages={usages} />);
    expect(screen.getByRole('dialog')).toHaveTextContent('v3');
    expect(screen.getByText('Index partially ready')).toBeInTheDocument();
    expect(screen.getByText('Indexed fragments: 8 / 10')).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.getByText(/Page-level extracted text is not available/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Original file' }));
    fireEvent.click(screen.getByRole('button', { name: 'Usage' }));
    expect(download).toHaveBeenCalledTimes(1);
    expect(usages).toHaveBeenCalledTimes(1);
  });

  it('does not call a deletion-pending source ready even if its index was ready', () => {
    render(<DocumentInspection document={{ ...document, lifecycle_status: 'deletion_pending', index: { ...document.index, status: 'ready' } }} lang="en" downloading={false} onClose={() => {}} onDownload={() => {}} onUsages={() => {}} />);
    expect(screen.getByText('Document is not active')).toBeInTheDocument();
    expect(screen.queryByText('Index ready')).not.toBeInTheDocument();
  });

  it('opens an existing draft without resuming or creating another generation job', () => {
    const retry = vi.fn();
    const cancel = vi.fn();
    const job: AIGenerationJob = { id: 'job-1', course_id: 'course-1', status: 'interrupted', stage: 'review', created_at: new Date().toISOString(), updated_at: new Date().toISOString(), progress: 60, message: 'Interrupted', queue_position: null, estimated_wait_seconds: null, tenant_active_jobs: null, tenant_active_limit: null };
    render(<GenerationProgressPanel job={job} stages={[]} title="Generation" labels={{ queued: 'Queued', running: 'Running', completed: 'Done', failed: 'Failed', cancelled: 'Cancelled', interrupted: 'Interrupted', stalled: 'Stalled' }} retryLabel="Continue" checkAgainLabel="Check again" cancelLabel="Cancel" cancelQueuedLabel="Cancel queued" queueTitle="Queue" activeJobs="Active" queuePosition="Position" estimatedWait="Wait" queueEstimateHint="Estimate" completedUnitsLabel="Saved" onRetry={retry} onCancel={cancel} lang="en" />);
    expect(screen.getByRole('link', { name: 'Open saved draft' })).toHaveAttribute('href', '/courses/course-1/edit');
    expect(screen.getByText(/Stages describe job execution, not independent content approval/)).toBeInTheDocument();
    expect(retry).not.toHaveBeenCalled();
    expect(cancel).not.toHaveBeenCalled();
  });
});
