"use client";

import AssignmentWorkbench from '@/features/methodologist-workbench/AssignmentWorkbench';
import DocumentWorkbench from '@/features/methodologist-workbench/DocumentWorkbench';
import { WorkspacePage, WorkspacePageHeader } from '@/features/workspace-design';
import { useAuthStore } from '@/store/authStore';
import { useLanguageStore } from '@/store/languageStore';
import { PanelsTopLeft } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui';

const TITLES = { ru: 'Рабочее место методиста', kk: 'Әдіскердің жұмыс орны', en: 'Methodologist workbench' } as const;
const WORKFLOWS = {
  ru: { assignment: 'Назначение', document: 'Документ' },
  kk: { assignment: 'Тағайындау', document: 'Құжат' },
  en: { assignment: 'Assignment', document: 'Document' },
} as const;

export default function MethodologistWorkbenchPage() {
  const role = useAuthStore((state) => state.user?.role);
  const lang = useLanguageStore((state) => state.lang);
  // The assignment surface retains its standalone heading contract. When it is
  // independently disabled, the page still has exactly one heading.
  const assignmentHeading = process.env.NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED === 'true' && role === 'methodologist';
  const hasBothWorkflows = assignmentHeading && process.env.NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED === 'true';
  const [workflow, setWorkflow] = useState<'assignment' | 'document'>('assignment');

  useEffect(() => {
    if (!hasBothWorkflows) return;
    const restoreWorkflow = () => {
      const query = new URLSearchParams(window.location.search);
      setWorkflow(query.has('document_task') || query.has('document_plan') ? 'document' : 'assignment');
    };
    restoreWorkflow();
    window.addEventListener('popstate', restoreWorkflow);
    return () => window.removeEventListener('popstate', restoreWorkflow);
  }, [hasBothWorkflows]);

  if (hasBothWorkflows) return <WorkspacePage id="methodologist-workbench" title={TITLES[lang]} icon={<PanelsTopLeft />}>
    <div role="group" aria-label={TITLES[lang]} className="flex flex-wrap gap-2">
      {(['assignment', 'document'] as const).map((item) => <Button key={item} type="button"
        aria-pressed={workflow === item} aria-controls={`workbench-${item}-panel`}
        variant={workflow === item ? 'secondary' : 'ghost'} onClick={() => setWorkflow(item)}>
        {WORKFLOWS[lang][item]}
      </Button>)}
    </div>
    <div id="workbench-assignment-panel" hidden={workflow !== 'assignment'}><AssignmentWorkbench showHeading={false} /></div>
    <div id="workbench-document-panel" hidden={workflow !== 'document'}><DocumentWorkbench /></div>
  </WorkspacePage>;

  return <WorkspacePage id="methodologist-workbench">
    {!assignmentHeading && <WorkspacePageHeader title={TITLES[lang]} icon={<PanelsTopLeft />} />}
    <AssignmentWorkbench />
    <DocumentWorkbench />
  </WorkspacePage>;
}
