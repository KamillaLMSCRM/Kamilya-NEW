import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import {
  DecisionPracticePlayer, parseDecisionPractice, type DecisionPractice,
} from '@/features/course-authoring/DecisionPractice';

const practice: DecisionPractice = {
  title: { ru: 'Приём смены', kk: 'Ауысымды қабылдау' },
  steps: [
    { id: 'first', text: { ru: 'Вы получили журнал', kk: 'Сіз журналды алдыңыз' }, choices: [
      { target: 'checked', label: { ru: 'Сверить записи', kk: 'Жазбаларды салыстыру' } },
      { target: 'signed', label: { ru: 'Подписать сразу', kk: 'Бірден қол қою' } },
    ] },
    { id: 'checked', text: { ru: 'Вы заметили пропуск', kk: 'Сіз бос жолды байқадыңыз' }, choices: [] },
    { id: 'signed', text: { ru: 'Пропуск остался', kk: 'Бос жол қалды' }, choices: [] },
  ],
};

afterEach(() => {
  cleanup();
  sessionStorage.clear();
});

it('follows both branches, restores the active step, and restarts in the selected language', () => {
  const player = render(<DecisionPracticePlayer practice={practice} language="ru" storageKey="enrollment/lesson/1" />);
  fireEvent.click(screen.getByRole('button', { name: 'Начать практику' }));
  fireEvent.click(screen.getByRole('button', { name: 'Сверить записи' }));
  expect(screen.getByText('Вы заметили пропуск')).toBeVisible();
  expect(screen.getByRole('heading', { name: 'Результат выбора' })).toHaveFocus();
  player.unmount();
  render(<DecisionPracticePlayer practice={practice} language="kk" storageKey="enrollment/lesson/1" />);
  expect(screen.getByText('Сіз бос жолды байқадыңыз')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Қайта бастау' }));
  fireEvent.click(screen.getByRole('button', { name: 'Бірден қол қою' }));
  expect(screen.getByText('Бос жол қалды')).toBeVisible();
});

it('starts a different revision cleanly and leaves previews out of learner storage', () => {
  sessionStorage.setItem('enrollment/lesson/1', 'checked');
  const newer = render(<DecisionPracticePlayer practice={practice} language="ru" storageKey="enrollment/lesson/2" />);
  expect(screen.getByRole('button', { name: 'Начать практику' })).toBeVisible();
  newer.unmount();
  render(<DecisionPracticePlayer practice={practice} language="ru" />);
  fireEvent.click(screen.getByRole('button', { name: 'Начать практику' }));
  fireEvent.click(screen.getByRole('button', { name: 'Подписать сразу' }));
  expect(sessionStorage.length).toBe(1);
  expect(sessionStorage.getItem('enrollment/lesson/1')).toBe('checked');
});

it('accepts a clean reviewer practice and drops disconnected or malformed snapshots', () => {
  expect(parseDecisionPractice(practice)).toEqual(practice);
  expect(parseDecisionPractice({ ...practice, steps: [...practice.steps, { ...practice.steps[1], id: 'isolated' }] })).toBeUndefined();
  expect(parseDecisionPractice({ ...practice, steps: [null] })).toBeUndefined();
});
