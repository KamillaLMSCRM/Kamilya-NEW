import Learner from '@/features/knowledge-checks/Learner';
export default async function Page({ params }: { params: Promise<{ assignmentId: string }> }) { const { assignmentId } = await params; return <Learner assignmentId={assignmentId} />; }
