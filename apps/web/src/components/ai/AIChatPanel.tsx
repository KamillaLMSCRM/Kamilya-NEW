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
  const { t } = useT();
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
          content: `Фокус рецензии: урок «${focusLessonTitle}». Спрашивай что угодно — могу переписать текст, проверить полноту, добавить примеры.`,
        });
      } else if (focusModuleId && focusModuleTitle) {
        focused.push({
          role: 'assistant',
          content: `Фокус рецензии: модуль «${focusModuleTitle}».`,
        });
      } else {
        focused.push({
          role: 'assistant',
          content: 'AI-помощник методолога. Спрашивай про структуру курса, проси переписать уроки, добавить контент.',
        });
      }
      setMessages(focused);
    }
  }, [open, focusLessonId, focusLessonTitle, focusModuleId, focusModuleTitle]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const sendMessage = async () => {
    if (!input.trim() || !token) return;
    const userText = input.trim();
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
      const target_id = focusLessonId || focusModuleId || null;

      const res = await fetch(`${API_URL}/v1/ai/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          course_id: courseId,
          context,
          target_id,
          message: userText,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: data.reply || '(пустой ответ)',
          apply_lesson_id: data.apply_lesson_id,
          apply_lesson_content: data.apply_lesson_content,
          apply_lesson_title_hint: data.apply_lesson_title_hint,
        },
      ]);
    } catch (e) {
      toast.error('Ошибка AI-чата');
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: '⚠️ Не удалось получить ответ. Попробуй ещё раз.' },
      ]);
    } finally {
      setSending(false);
    }
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
      toast.success('Урок обновлён');
      onLessonApplied?.();
    } catch (e) {
      toast.error('Не удалось применить правку');
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
        aria-label="AI-помощник методолога"
      >
        <header className="flex items-center justify-between px-4 py-3 border-b border-border">
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-primary" />
            <h2 className="font-semibold">AI-помощник</h2>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            <X className="w-4 h-4" />
          </Button>
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
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
                    ✏️ Предложение замены урока
                    {m.apply_lesson_title_hint ? `: «${m.apply_lesson_title_hint}»` : ''}
                  </div>
                  <pre className="text-xs whitespace-pre-wrap max-h-40 overflow-y-auto bg-muted/50 p-2 rounded">
                    {m.apply_lesson_content}
                  </pre>
                  {m.applied_lesson_id === m.apply_lesson_id ? (
                    <Badge variant="secondary">✓ Применено</Badge>
                  ) : (
                    <Button size="sm" variant="default" onClick={() => applySuggestion(m)}>
                      Применить к уроку
                    </Button>
                  )}
                </div>
              )}
            </div>
          ))}
          {sending && (
            <div className="text-sm text-muted-foreground">AI думает…</div>
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
                  ? 'Попроси AI переписать этот урок…'
                  : 'Спросить AI…'
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