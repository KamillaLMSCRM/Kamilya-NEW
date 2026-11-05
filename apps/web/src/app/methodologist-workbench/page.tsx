"use client";

import AssignmentWorkbench from '@/features/methodologist-workbench/AssignmentWorkbench';
import DocumentWorkbench from '@/features/methodologist-workbench/DocumentWorkbench';
import { WorkspacePage, WorkspacePageHeader } from '@/features/workspace-design';
import { useAuthStore } from '@/store/authStore';
import { useLanguageStore } from '@/store/languageStore';
import { PanelsTopLeft } from 'lucide-react';

const TITLES = { ru: 'Рабочее место методиста', kk: 'Әдіскердің жұмыс орны', en: 'Methodologist workbench' } as const;

export default function MethodologistWorkbenchPage() {
  const role = useAuthStore((state) => state.user?.role);
  const lang = useLanguageStore((state) => state.lang);
  // The assignment surface retains its standalone heading contract. When it is
  // independently disabled, the page still has exactly one heading.
  const assignmentHeading = process.env.NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED === 'true' && role === 'methodologist';
  return <WorkspacePage id="methodologist-workbench">
    {!assignmentHeading && <WorkspacePageHeader title={TITLES[lang]} icon={<PanelsTopLeft />} />}
    <AssignmentWorkbench />
    <DocumentWorkbench />
  </WorkspacePage>;
}
