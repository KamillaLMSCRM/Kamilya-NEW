'use client';

import { useState } from 'react';
import { exampleCopy, type ExampleLanguage } from './copy';

export function ProductExample({ language = 'ru' }: { language?: ExampleLanguage }) {
  const c = exampleCopy[language];
  const [answer, setAnswer] = useState<number | null>(null);
  const [checked, setChecked] = useState(false);
  const [detail, setDetail] = useState<number | null>(null);
  const linkStyle = 'rounded-lg border border-border px-4 py-3 text-sm font-semibold hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary';

  return (
    <main id="main-content" lang={language} className="min-h-screen bg-background px-4 py-6 text-foreground sm:px-8">
      <div className="mx-auto max-w-6xl">
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-5">
          <a href="/login" className="text-xl font-bold">Kamilya LMS</a>
          <nav aria-label="Language" className="flex gap-3 text-sm">
            {(['ru', 'kk', 'en'] as const).map(lang => <a key={lang} href={`/login/example?lang=${lang}`} lang={lang} aria-current={language === lang ? 'page' : undefined} className={language === lang ? 'font-bold text-primary underline underline-offset-4' : ''}>{lang === 'ru' ? 'Русский' : lang === 'kk' ? 'Қазақша' : 'English'}</a>)}
          </nav>
        </header>
        <section className="py-8 sm:py-10">
          <p className="mb-3 text-sm font-semibold text-primary">{c.label}</p>
          <h1 className="text-3xl font-bold tracking-tight sm:text-5xl">{c.title}</h1>
          <p className="mt-4 max-w-3xl text-lg text-muted-foreground">{c.intro}</p>
        </section>
        <div className="grid gap-6 lg:grid-cols-2">
          <section aria-labelledby="example-lesson" className="rounded-2xl border border-border bg-card p-5 sm:p-7">
            <h2 id="example-lesson" className="text-sm font-semibold text-primary">{c.lesson}</h2>
            <p className="mt-5 text-sm text-muted-foreground">{c.course}</p>
            <h3 className="mt-2 text-2xl font-semibold">{c.lessonTitle}</h3>
            {c.paragraphs.map(p => <p key={p} className="mt-4 leading-7">{p}</p>)}
            <p className="mt-6 border-t border-border pt-4 text-sm leading-6 text-muted-foreground">{c.caveat}</p>
          </section>
          <section aria-labelledby="example-question" className="rounded-2xl border border-border bg-card p-5 sm:p-7">
            <h2 id="example-question" className="text-sm font-semibold text-primary">{c.question}</h2>
            <fieldset className="mt-5" disabled={checked}>
              <legend className="text-xl font-semibold">{c.prompt}</legend>
              <div className="mt-4 space-y-3">
                {c.options.map((option, index) => <label key={option} className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 leading-6 ${answer === index ? 'border-primary bg-primary/5' : 'border-border'}`}><input type="radio" name="example-answer" value={index} checked={answer === index} onChange={() => setAnswer(index)} className="mt-1.5" />{option}</label>)}
              </div>
            </fieldset>
            <div className="mt-5 flex flex-wrap gap-3">
              <button type="button" disabled={answer === null || checked} onClick={() => setChecked(true)} className="rounded-lg bg-primary px-4 py-3 text-sm font-semibold text-primary-foreground disabled:opacity-40">{c.check}</button>
              {checked && <button type="button" className={linkStyle} onClick={() => { setChecked(false); setAnswer(null); }}>{c.retry}</button>}
            </div>
            <div aria-live="polite">{checked && <p className="mt-4 border-l-4 border-primary bg-muted p-4 leading-6">{answer === 1 ? c.correct : c.incorrect}</p>}</div>
            <p className="mt-4 text-sm text-muted-foreground">{c.local}</p>
          </section>
        </div>
        <section aria-labelledby="example-results" className="py-9">
          <h2 id="example-results" className="text-2xl font-semibold">{c.results}</h2>
          <p className="mt-3 text-sm text-muted-foreground">{c.resultNote}</p>
          <div className="mt-5 grid gap-4 md:grid-cols-3">
            {c.rows.map((row, index) => <article key={row.person} className="rounded-xl border border-border bg-card p-5">
              <h3 className="font-semibold">{row.person}</h3>
              <p className={`mt-3 font-semibold ${index === 0 ? 'text-green-700 dark:text-green-400' : index === 1 ? 'text-amber-700 dark:text-amber-400' : 'text-red-700 dark:text-red-400'}`}>{row.status}</p>
              <p className="mt-1 text-sm text-muted-foreground">{row.score}</p>
              <button type="button" aria-expanded={detail === index} aria-controls={`example-detail-${index}`} className="mt-5 text-left text-sm font-semibold text-primary underline underline-offset-4" onClick={() => setDetail(detail === index ? null : index)}>{row.action}</button>
              {detail === index && <p id={`example-detail-${index}`} className="mt-3 text-sm leading-6">{row.detail}</p>}
            </article>)}
          </div>
        </section>
        <section aria-labelledby="example-start" className="border-t border-border py-8">
          <h2 id="example-start" className="text-2xl font-semibold">{c.start}</h2>
          <div className="mt-5 grid gap-6 sm:grid-cols-2">{c.paths.map(path => <div key={path.title}><h3 className="font-semibold">{path.title}</h3><p className="mt-2 leading-7 text-muted-foreground">{path.body}</p></div>)}</div>
          <p className="mt-6 max-w-4xl text-sm leading-6">{c.responsibility}</p>
          <div className="mt-6 flex flex-wrap gap-3"><a href="/register-tenant" className="rounded-lg bg-primary px-4 py-3 text-sm font-semibold text-primary-foreground">{c.trial}</a><a href="/login/demo" className={linkStyle}>{c.demo}</a><a href="/login" className={linkStyle}>{c.login}</a></div>
        </section>
      </div>
    </main>
  );
}
