import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';

export type PracticeLanguage = 'ru' | 'kk';
export type Bilingual = Record<PracticeLanguage, string>;
export type PracticeChoice = { label: Bilingual; target: string };
export type PracticeStep = { id: string; text: Bilingual; choices: PracticeChoice[] };
export type DecisionPractice = { title: Bilingual; steps: PracticeStep[] };
export type PracticeEdition = { revision: string; practice: DecisionPractice };

const messages = {
  ru: {
    name: 'Тренажёр решений', start: 'Начать практику', resume: 'Продолжить практику',
    restart: 'Начать заново', outcome: 'Результат выбора', step: 'Шаг', edit: 'Настроить тренажёр',
    create: 'Добавить тренажёр', title: 'Название практики', language: 'Язык текста',
    text: 'Текст шага', ending: 'Разбор в конце ветки', answer: 'Вариант действия', target: 'Следующий шаг',
    addStep: 'Добавить шаг', addChoice: 'Добавить вариант', remove: 'Удалить', save: 'Сохранить тренажёр',
    saved: 'Тренажёр сохранён', cancel: 'Отменить правки', preview: 'Проверить ветки', back: 'Вернуться к редактированию',
    delete: 'Удалить тренажёр', confirmDelete: 'Удалить тренажёр из черновика урока?',
    invalid: 'Заполните русский и казахский текст. У первого шага должно быть два разных перехода. Все шаги должны быть достижимы и вести к завершению без циклов.',
    failed: 'Не удалось загрузить или сохранить тренажёр.', conflict: 'Тренажёр изменился. Загрузите сохранённую версию перед повторным сохранением.',
    reload: 'Загрузить сохранённую версию', loading: 'Загрузка тренажёра…',
  },
  kk: {
    name: 'Шешім қабылдау жаттықтырғышы', start: 'Жаттығуды бастау', resume: 'Жаттығуды жалғастыру',
    restart: 'Қайта бастау', outcome: 'Таңдау нәтижесі', step: 'Қадам', edit: 'Жаттықтырғышты баптау',
    create: 'Жаттықтырғыш қосу', title: 'Жаттығу атауы', language: 'Мәтін тілі',
    text: 'Қадам мәтіні', ending: 'Тармақ соңындағы түсіндірме', answer: 'Әрекет нұсқасы', target: 'Келесі қадам',
    addStep: 'Қадам қосу', addChoice: 'Нұсқа қосу', remove: 'Жою', save: 'Жаттықтырғышты сақтау',
    saved: 'Жаттықтырғыш сақталды', cancel: 'Өзгерістерден бас тарту', preview: 'Тармақтарды тексеру', back: 'Өңдеуге оралу',
    delete: 'Жаттықтырғышты жою', confirmDelete: 'Жаттықтырғышты сабақ нобайынан жою керек пе?',
    invalid: 'Мәтінді орыс және қазақ тілдерінде толтырыңыз. Бірінші қадам екі бөлек бағытқа өтуі керек. Барлық қадамдарға жетуге және жаттығуды циклсіз аяқтауға болуға тиіс.',
    failed: 'Жаттықтырғышты жүктеу немесе сақтау мүмкін болмады.', conflict: 'Жаттықтырғыш өзгерді. Қайта сақтамас бұрын сақталған нұсқаны жүктеңіз.',
    reload: 'Сақталған нұсқаны жүктеу', loading: 'Жаттықтырғыш жүктелуде…',
  },
  en: {
    name: 'Decision practice', start: 'Start practice', resume: 'Resume practice',
    restart: 'Start over', outcome: 'Decision outcome', step: 'Step', edit: 'Configure practice',
    create: 'Add practice', title: 'Practice title', language: 'Content language',
    text: 'Step text', ending: 'End-of-branch feedback', answer: 'Action', target: 'Next step',
    addStep: 'Add step', addChoice: 'Add action', remove: 'Remove', save: 'Save practice',
    saved: 'Practice saved', cancel: 'Discard changes', preview: 'Try the branches', back: 'Back to editing',
    delete: 'Delete practice', confirmDelete: 'Delete this practice from the lesson draft?',
    invalid: 'Enter Russian and Kazakh text. The first step needs two different destinations. Every step must be reachable and lead to an ending without a loop.',
    failed: 'The practice could not be loaded or saved.', conflict: 'The practice changed. Reload the saved version before saving again.',
    reload: 'Reload saved version', loading: 'Loading practice…',
  },
};

export const practiceCopy = (language: string) => language === 'kk' ? messages.kk
  : language === 'en' ? messages.en : messages.ru;

export function parseDecisionPractice(value: unknown): DecisionPractice | undefined {
  const record = (input: unknown): input is Record<string, unknown> =>
    typeof input === 'object' && input !== null && !Array.isArray(input);
  const text = (input: unknown): input is Bilingual =>
    record(input) && typeof input.ru === 'string' && typeof input.kk === 'string';
  if (!record(value) || !text(value.title) || !Array.isArray(value.steps)) return undefined;
  const steps: PracticeStep[] = [];
  for (const step of value.steps) {
    if (!record(step) || typeof step.id !== 'string' || !text(step.text) || !Array.isArray(step.choices)) return undefined;
    const choices: PracticeChoice[] = [];
    for (const choice of step.choices) {
      if (!record(choice) || !text(choice.label) || typeof choice.target !== 'string') return undefined;
      choices.push({ label: choice.label, target: choice.target });
    }
    steps.push({ id: step.id, text: step.text, choices });
  }
  const practice = { title: value.title, steps };
  return validDecisionPractice(practice) ? practice : undefined;
}

export function validDecisionPractice(practice: DecisionPractice) {
  const filled = (copy: Bilingual) => Boolean(copy.ru.trim() && copy.kk.trim());
  const steps = new Map(practice.steps.map(step => [step.id, step]));
  const first = practice.steps[0];
  if (!first || practice.steps.length < 3 || practice.steps.length > 12 || steps.size !== practice.steps.length
    || !filled(practice.title) || new Set(first.choices.map(choice => choice.target)).size < 2) return false;
  const visited = new Set<string>();
  const active = new Set<string>();
  const visit = (step: PracticeStep): boolean => {
    if (active.has(step.id)) return false;
    if (visited.has(step.id)) return true;
    if (!filled(step.text) || step.choices.length > 4) return false;
    const labels = (lang: PracticeLanguage) => new Set(step.choices.map(choice => choice.label[lang].trim().toLowerCase()));
    if (labels('ru').size !== step.choices.length || labels('kk').size !== step.choices.length) return false;
    active.add(step.id);
    for (const choice of step.choices) {
      const next = steps.get(choice.target);
      if (!next || !filled(choice.label) || !visit(next)) return false;
    }
    active.delete(step.id);
    visited.add(step.id);
    return true;
  };
  return visit(first) && visited.size === practice.steps.length;
}

export function DecisionPracticePlayer({ practice, language, storageKey }: {
  practice: DecisionPractice; language: string; storageKey?: string;
}) {
  const lang = language === 'kk' ? 'kk' : 'ru';
  const copy = practiceCopy(language);
  const heading = useRef<HTMLHeadingElement>(null);
  const moved = useRef(false);
  const [position, setPosition] = useState<string | null>(null);

  useEffect(() => {
    if (!storageKey) return;
    try {
      const saved = sessionStorage.getItem(storageKey);
      if (practice.steps.some(step => step.id === saved)) setPosition(saved);
    } catch { /* Browser storage is optional. */ }
  }, [practice, storageKey]);

  useEffect(() => {
    if (moved.current) heading.current?.focus();
  }, [position]);

  function go(id: string) {
    moved.current = true;
    setPosition(id);
    if (storageKey) {
      try { sessionStorage.setItem(storageKey, id); } catch { /* Keep the step in memory. */ }
    }
  }

  const first = practice.steps[0];
  const step = practice.steps.find(item => item.id === position);
  return <section aria-label={copy.name} className="space-y-4 rounded-xl border border-primary/20 bg-card p-4 sm:p-6">
    <p className="text-sm font-medium text-muted-foreground">{copy.name}</p>
    <h2 ref={heading} tabIndex={-1} className="break-words text-lg font-semibold outline-none" aria-live="polite">
      {step && !step.choices.length ? copy.outcome : practice.title[lang]}
    </h2>
    {step ? <>
      <p className="whitespace-pre-wrap break-words text-sm leading-6">{step.text[lang]}</p>
      <div className="grid gap-2">
        {step.choices.map((choice, index) => <Button key={index} type="button" variant="outline"
          className="h-auto min-h-11 justify-start whitespace-normal text-left" onClick={() => go(choice.target)}>
          {choice.label[lang]}
        </Button>)}
      </div>
      <Button type="button" variant="ghost" onClick={() => go(first.id)}>{copy.restart}</Button>
    </> : <Button type="button" onClick={() => go(first.id)}>{copy.start}</Button>}
  </section>;
}
