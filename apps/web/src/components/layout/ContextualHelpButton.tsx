'use client';

import { useState } from 'react';
import { CircleHelp, Lightbulb, ListChecks, ShieldAlert } from 'lucide-react';
import { usePathname } from 'next/navigation';

import { Modal } from '@/components/ui';
import { useT } from '@/i18n/useT';
import { getContextualHelp } from '@/lib/contextualHelp';
import { useAuthStore } from '@/store/authStore';

const CHROME = {
  ru: { button: 'Справка', steps: 'Как использовать', example: 'Пример', result: 'Что получится', important: 'Важно' },
  kk: { button: 'Анықтама', steps: 'Қалай пайдалану керек', example: 'Мысал', result: 'Нәтиже', important: 'Маңызды' },
  en: { button: 'Help', steps: 'How to use it', example: 'Example', result: 'Expected result', important: 'Important' },
} as const;

export function ContextualHelpButton() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const role = useAuthStore((state) => state.user?.role);
  const { lang } = useT();
  const locale = lang in CHROME ? lang as keyof typeof CHROME : 'ru';
  const labels = CHROME[locale];
  const help = getContextualHelp(pathname, role, locale);

  if (!help) return null;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex h-10 items-center gap-2 rounded-xl border border-primary/25 bg-primary/5 px-3 text-sm font-semibold text-primary transition-colors hover:border-primary/50 hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={`${labels.button}: ${help.title}`}
        title={`${labels.button}: ${help.title}`}
      >
        <CircleHelp className="h-4 w-4" aria-hidden="true" />
        <span className="hidden lg:inline">{labels.button}</span>
      </button>
      <Modal
        open={open}
        onOpenChange={setOpen}
        title={help.title}
        description={help.purpose}
        className="max-w-3xl"
      >
        <div className="space-y-5 text-sm text-foreground">
          <section>
            <h3 className="mb-3 flex items-center gap-2 font-bold"><ListChecks className="h-4 w-4 text-primary" aria-hidden="true" />{labels.steps}</h3>
            <ol className="space-y-2">
              {help.steps.map((step, index) => (
                <li key={step} className="flex gap-3 rounded-lg border border-border/70 px-3 py-2.5">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-bold text-primary-foreground">{index + 1}</span>
                  <span className="leading-6">{step}</span>
                </li>
              ))}
            </ol>
          </section>
          <div className="grid gap-3 md:grid-cols-2">
            <section className="rounded-xl border border-border p-4">
              <h3 className="mb-2 flex items-center gap-2 font-bold"><Lightbulb className="h-4 w-4 text-warning" aria-hidden="true" />{labels.example}</h3>
              <p className="leading-6 text-muted-foreground">{help.example}</p>
            </section>
            <section className="rounded-xl border border-success/25 bg-success/5 p-4">
              <h3 className="mb-2 font-bold text-success">{labels.result}</h3>
              <p className="leading-6 text-muted-foreground">{help.result}</p>
            </section>
          </div>
          <section className="rounded-xl border border-warning/30 bg-warning/5 p-4">
            <h3 className="mb-2 flex items-center gap-2 font-bold text-warning"><ShieldAlert className="h-4 w-4" aria-hidden="true" />{labels.important}</h3>
            <p className="leading-6 text-muted-foreground">{help.important}</p>
          </section>
        </div>
      </Modal>
    </>
  );
}
