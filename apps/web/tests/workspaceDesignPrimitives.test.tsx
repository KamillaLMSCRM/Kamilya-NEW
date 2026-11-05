import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PublicWorkspace, WorkspaceEmpty, WorkspacePage, WorkspacePanel, WorkspaceStat, WorkspaceToolbar } from '@/features/workspace-design';

describe('whole workspace presentation primitives', () => {
  it('keeps real action handlers, content and page identity without inventing state', () => {
    const save = vi.fn();
    const { container } = render(<WorkspacePage id="test-workspace" title="Existing title" description="Existing description" actions={<button onClick={save}>Save</button>}>
      <WorkspaceToolbar role="search" aria-label="Existing filters"><input aria-label="Query" /></WorkspaceToolbar>
      <WorkspacePanel title="Existing section"><p>Existing record</p></WorkspacePanel>
    </WorkspacePage>);
    expect(container.querySelector('[data-redesign-page="test-workspace"]')).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByRole('search', { name: 'Existing filters' })).toBeInTheDocument();
    expect(screen.getByText('Existing record')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(save).toHaveBeenCalledExactlyOnceWith(expect.anything());
  });

  it('distinguishes a known zero from unknown metrics', () => {
    const { container } = render(<><WorkspaceStat label="Known" value={0} /><WorkspaceStat label="Unknown" value={null} /></>);
    const stats = container.querySelectorAll('[data-workspace-stat]');
    expect(stats[0]).toHaveTextContent('0');
    expect(stats[1]).toHaveTextContent('—');
    expect(stats[1]).not.toHaveTextContent('0');
  });

  it('provides an empty state without an implicit create command', () => {
    render(<WorkspaceEmpty title="Confirmed empty" description="Existing hint" />);
    expect(screen.getByRole('heading', { name: 'Confirmed empty' })).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('does not add a home link or account actions to bounded public access', () => {
    render(<PublicWorkspace id="bounded-public" title="Existing access form"><label>Code<input /></label></PublicWorkspace>);
    expect(screen.getByRole('main')).toHaveAttribute('data-redesign-page', 'bounded-public');
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
