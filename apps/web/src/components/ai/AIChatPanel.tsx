'use client';

import { useState, useRef, useEffect } from 'react';
import { Button, Input, Badge } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { toast } from '@/components/ui/Toast';
import { X, Send, Sparkles } from 'lucide-react';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  apply_lesson_id?: string;
  apply_lesson_content?: string;
  apply_lesson_title_hint?: string;
  applied_lesson_id?: string;
  audience_recommendation?: AudienceRecommendation;
}

interface AudienceScope {
  type: 'organization' | 'department' | 'position' | 'cohort';
  id?: string | null;
  name: string;
  employee_count: number;
  priority: 'primary' | 'secondary';
  confidence: 'high' | 'medium' | 'low';
  reasons: string[];
}

interface AudienceRecommendation {
  course_status: 'draft' | 'review' | 'published' | 'archived';
  recommended_scopes: AudienceScope[];
  matched_employee_count: number;
  already_enrolled_count: number;
  data_warnings: string[];
  assignment_url?: string | null;
}

interface AIChatPanelProps {
  open: boolean;
  onClose: () => void;
  courseId: string;
  // Optional: lesson to focus on
  focusLessonId?: string;
  focusLessonTitle?: string;
  // Optional: module to focus on
  focusModuleId?: string;
  focusModuleTitle?: string;
  // Triggered when AI suggests a lesson edit and user clicks Apply
  onLessonApplied?: () => void;
}

export function AIChatPanel({
  open,
  onClose,
  courseId,
  focusLessonId,
  focusLessonTitle,
  focusModuleId,
  focusModuleTitle,
  onLessonApplied,
}: AIChatPanelProps) {
  const { t, lang } = useT();
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Reset chat when panel opens; prefill with focus context if provided.
  useEffect(() => {
    if (open) {
      const focused: ChatMessage[] = [];
      if (focusLessonId && focusLessonTitle) {
        focused.push({
          role: 'assistant',
          content: t('aiAssistant.focusLesson', { title: focusLessonTitle }),
        });
      } else if (focusModuleId && focusModuleTitle) {
        focused.push({
          role: 'assistant',
          content: t('aiAssistant.focusModule', { title: focusModuleTitle }),
        });
      } else {
        focused.push({
          role: 'assistant',
          content: t('aiAssistant.intro'),
        });
      }
      setMessages(focused);
    }
  }, [open, focusLessonId, focusLessonTitle, focusModuleId, focusModuleTitle, t]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const sendMessage = async (messageOverride?: string, intent?: 'audience_recommendation') => {
    const userText = (messageOverride ?? input).trim();
    if (!userText || !token) return;
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', content: userText }]);
    setSending(true);
    try {
      // Build chat payload — chat endpoint takes context/target_id, not lesson_focus_id
      const context = focusLessonId
        ? 'lesson'
        : focusModuleId
        ? 'module'
        : 'course';
      const isAudienceIntent = intent === 'audience_recommendation';
      const requestContext = isAudienceIntent ? 'course' : context;
      const target_id = isAudienceIntent ? null : focusLessonId || focusModuleId || null;

      const res = await fetch(`${API_URL}/v1/ai/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          course_id: courseId,
          context: requestContext,
          target_id,
          message: userText,
          language: lang,
          intent,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: data.reply || t('aiAssistant.emptyReply'),
          apply_lesson_id: data.apply_lesson_id,
          apply_lesson_content: data.apply_lesson_content,
          apply_lesson_title_hint: data.apply_lesson_title_hint,
          audience_recommendation: data.audience_recommendation,
        },
      ]);
    } catch (e) {
      toast.error(t('aiAssistant.errorToast'));
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: t('aiAssistant.errorReply') },
      ]);
    } finally {
      setSending(false);
    }
  };

  const scopeLabel: Record<AudienceScope['type'], string> = {
    organization: t('aiAssistant.organization'),
    department: t('aiAssistant.department'),
    position: t('aiAssistant.position'),
    cohort: t('aiAssistant.cohort'),
  };

  const reasonLabel = (code: string) => t(`aiAssistant.reason.${code}` as any);
  const warningLabel = (code: string) => t(`aiAssistant.warning.${code}` as any);

  const renderAudienceRecommendation = (recommendation: AudienceRecommendation) => {
    const primary = recommendation.recommended_scopes.filter((scope) => scope.priority === 'primary');
    const secondary = recommendation.recommended_scopes.filter((scope) => scope.priority === 'secondary');
    const renderScopes = (scopes: AudienceScope[]) => scopes.map((scope) => (
      <div key={`${scope.type}-${scope.id ?? scope.name}`} className="rounded-md border border-border p-2 space-y-1">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="text-xs text-muted-foreground">{scopeLabel[scope.type]}</div>
            <div className="font-medium truncate">{scope.name}</div>
          </div>
          <Badge variant="secondary">{scope.employee_count}</Badge>
        </div>
        <div className="text-xs text-muted-foreground">{t('aiAssistant.confidence.' + scope.confidence as any)}</div>
        {scope.reasons.length > 0 && (
          <ul className="text-xs text-muted-foreground list-disc pl-4 space-y-0.5">
            {scope.reasons.map((reason) => <li key={reason}>{reasonLabel(reason)}</li>)}
          </ul>
        )}
      </div>
    ));

    return (
      <div className="w-full border border-primary/30 rounded-lg p-3 space-y-3 bg-background" data-testid="audience-recommendation">
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge variant="secondary">{recommendation.course_status === 'published' ? t('aiAssistant.published') : t('aiAssistant.notPublished')}</Badge>
          <Badge variant="outline">{t('aiAssistant.matched', { count: recommendation.matched_employee_count })}</Badge>
          <Badge variant="outline">{t('aiAssistant.alreadyAssigned', { count: recommendation.already_enrolled_count })}</Badge>
        </div>
        {primary.length > 0 && (
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">{t('aiAssistant.primary')}</h3>
            {renderScopes(primary)}
          </section>
        )}
        {secondary.length > 0 && (
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">{t('aiAssistant.secondary')}</h3>
            {renderScopes(secondary)}
          </section>
        )}
        {recommendation.data_warnings.length > 0 && (
          <section className="rounded-md bg-muted/50 p-2 space-y-1">
            <h3 className="text-xs font-semibold">{t('aiAssistant.warnings')}</h3>
            {recommendation.data_warnings.map((warning) => <p className="text-xs text-muted-foreground" key={warning}>{warningLabel(warning)}</p>)}
          </section>
        )}
        {recommendation.course_status !== 'published' && (
          <p className="text-xs text-muted-foreground">{t('aiAssistant.reviewHint')}</p>
        )}
        {recommendation.assignment_url && recommendation.course_status === 'published' && (
          <a
            href={recommendation.assignment_url}
            className="inline-flex items-center justify-center rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            {t('aiAssistant.openAssignments')}
          </a>
        )}
      </div>
    );
  };

  const applySuggestion = async (msg: ChatMessage) => {
    if (!msg.apply_lesson_id || !msg.apply_lesson_content || !token) return;
    try {
      const res = await fetch(`${API_URL}/v1/lessons/${msg.apply_lesson_id}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ content: msg.apply_lesson_content }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      // Mark as applied in chat
      setMessages((prev) =>
        prev.map((m, i) =>
          m === msg ? { ...m, applied_lesson_id: msg.apply_lesson_id } : m
        )
      );
      toast.success(t('aiAssistant.lessonUpdated'));
      onLessonApplied?.();
    } catch (e) {
      toast.error(t('aiAssistant.applyError'));
    }
  };

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/30 z-40"
        onClick={onClose}
        aria-hidden="true"
      />
      {/* Side panel */}
      <aside
        className="fixed right-0 top-0 bottom-0 w-[480px] max-w-[90vw] bg-background border-l border-border shadow-xl z-50 flex flex-col"
        role="dialog"
        aria-label={t('aiAssistant.dialogLabel')}
      >
        <header className="flex items-center justify-between px-4 py-3 border-b border-border">
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-primary" />
            <h2 className="font-semibold">{t('aiAssistant.title')}</h2>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            <X className="w-4 h-4" />
          </Button>
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
          {messages.length <= 1 && (
            <button
              type="button"
              className="w-full text-left rounded-lg border border-primary/30 px-3 py-2 text-sm hover:bg-muted"
              onClick={() => sendMessage(t('aiAssistant.audienceQuestion'), 'audience_recommendation')}
              disabled={sending}
            >
              {t('aiAssistant.audienceQuestion')}
            </button>
          )}
          {messages.map((m, i) => (
            <div
              key={i}
              className={
                m.role === 'user'
                  ? 'flex justify-end'
                  : 'flex flex-col items-start gap-2'
              }
            >
              <div
                className={
                  m.role === 'user'
                    ? 'bg-primary text-primary-foreground rounded-lg px-3 py-2 max-w-[85%] text-sm whitespace-pre-wrap'
                    : 'bg-muted rounded-lg px-3 py-2 max-w-[90%] text-sm whitespace-pre-wrap'
                }
              >
                {m.content}
              </div>
              {m.role === 'assistant' && m.apply_lesson_id && m.apply_lesson_content && (
                <div className="bg-background border border-primary/40 rounded-lg p-3 max-w-[90%] space-y-2">
                  <div className="text-xs font-medium text-primary">
                    {m.apply_lesson_title_hint
                      ? t('aiAssistant.lessonSuggestionWithTitle', { title: m.apply_lesson_title_hint })
                      : t('aiAssistant.lessonSuggestion')}
                  </div>
                  <pre className="text-xs whitespace-pre-wrap max-h-40 overflow-y-auto bg-muted/50 p-2 rounded">
                    {m.apply_lesson_content}
                  </pre>
                  {m.applied_lesson_id === m.apply_lesson_id ? (
                    <Badge variant="secondary">{t('aiAssistant.applied')}</Badge>
                  ) : (
                    <Button size="sm" variant="default" onClick={() => applySuggestion(m)}>
                      {t('aiAssistant.applyLesson')}
                    </Button>
                  )}
                </div>
              )}
              {m.role === 'assistant' && m.audience_recommendation && renderAudienceRecommendation(m.audience_recommendation)}
            </div>
          ))}
          {sending && (
            <div className="text-sm text-muted-foreground">{t('aiAssistant.thinking')}</div>
          )}
        </div>

        <footer className="border-t border-border p-3">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              sendMessage();
            }}
            className="flex gap-2"
          >
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={
                focusLessonId
                  ? t('aiAssistant.lessonPlaceholder')
                  : t('aiAssistant.chatPlaceholder')
              }
              disabled={sending}
              autoFocus
            />
            <Button type="submit" disabled={sending || !input.trim()}>
              <Send className="w-4 h-4" />
            </Button>
          </form>
        </footer>
      </aside>
    </>
  );
}
