import { attemptChoiceOrder } from '@/lib/attemptChoiceOrder';
import { Button, Input } from '@/components/ui';

export const MATCHING_PAIRS = 'matching_pairs';

export type MatchingChoice = { id: string; text: string; match_side?: 'left' | 'right' | null };

const copy = {
  ru: { type: 'Сопоставление пар', left: 'Левая часть', right: 'Правая часть', add: 'Добавить пару',
    remove: 'Удалить пару', choose: 'Выберите пару', authorHint: 'Введите правильные пары по строкам.',
    invalid: 'Добавьте от 2 до 25 заполненных пар. В каждой колонке варианты должны различаться.',
    learnerHint: 'Выберите соответствие для каждого пункта. Каждый вариант можно использовать один раз.' },
  kk: { type: 'Жұптарды сәйкестендіру', left: 'Сол жақ бөлік', right: 'Оң жақ бөлік', add: 'Жұп қосу',
    remove: 'Жұпты жою', choose: 'Жұбын таңдаңыз', authorHint: 'Әр жолға дұрыс жұпты енгізіңіз.',
    invalid: '2–25 толық жұп қосыңыз. Әр бағандағы нұсқалар әртүрлі болуы керек.',
    learnerHint: 'Әр тармаққа жұп таңдаңыз. Әр нұсқаны бір рет қолдануға болады.' },
  en: { type: 'Matching pairs', left: 'Left item', right: 'Right item', add: 'Add pair',
    remove: 'Remove pair', choose: 'Choose a match', authorHint: 'Enter one correct pair per row.',
    invalid: 'Enter 2 to 25 complete pairs. Use distinct choices in each column.',
    learnerHint: 'Choose a match for each item. Each option can be used once.' },
};

export function matchingCopy(language: string) {
  return language === 'ru' ? copy.ru : language === 'kk' ? copy.kk : copy.en;
}

export function validMatchingChoices(choices: readonly { text: string }[]) {
  if (choices.length < 4 || choices.length > 50 || choices.length % 2) return false;
  const labels = choices.map(({ text }) => text.trim().toLowerCase());
  if (labels.includes('')) return false;
  return [0, 1].every((side) => new Set(labels.filter((_, index) => index % 2 === side)).size === choices.length / 2);
}

export function matchingSelection(choices: readonly MatchingChoice[], selected: readonly string[] = []) {
  const sides = new Map(choices.map((choice) => [choice.id, choice.match_side]));
  const result = new Map<string, string>();
  const used = new Set<string>();
  for (let index = 0; index + 1 < selected.length; index += 2) {
    const [left, right] = [selected[index], selected[index + 1]];
    if (sides.get(left) === 'left' && sides.get(right) === 'right' && !result.has(left) && !used.has(right)) {
      result.set(left, right);
      used.add(right);
    }
  }
  return result;
}

export function hasQuizAnswer(question: { type: string; choices: readonly MatchingChoice[] }, ids?: readonly string[]) {
  return question.type === MATCHING_PAIRS
    ? question.choices.length >= 4 && matchingSelection(question.choices, ids).size * 2 === question.choices.length
    : Boolean(ids?.length);
}

export function MatchingAnswer({ choices, selected, scope, questionId, attempt, language, disabled, onChange }: {
  choices: readonly MatchingChoice[];
  selected?: readonly string[];
  scope: string;
  questionId: string;
  attempt: number;
  language: string;
  disabled?: boolean;
  onChange: (selected: string[]) => void;
}) {
  const labels = matchingCopy(language);
  const left = attemptChoiceOrder(choices.filter((choice) => choice.match_side === 'left'), scope, questionId, 0);
  const right = attemptChoiceOrder(choices.filter((choice) => choice.match_side === 'right'), scope, questionId, attempt);
  const pairs = matchingSelection(choices, selected);
  const used = new Set(pairs.values());

  return <div className="min-w-0 space-y-3">
    <p className="text-sm text-muted-foreground">{labels.learnerHint}</p>
    {left.map((item) => (
      <label key={item.id} className="grid min-w-0 gap-2 rounded-xl border border-border bg-card p-3 sm:grid-cols-2 sm:items-center">
        <span className="min-w-0 break-words text-sm font-medium">{item.text}</span>
        <select value={pairs.get(item.id) ?? ''} disabled={disabled}
          className="min-h-11 w-full min-w-0 rounded-lg border border-input bg-background px-2 text-sm focus-visible:outline-primary"
          onChange={(event) => {
            const value = event.target.value;
            if (value) pairs.set(item.id, value);
            else pairs.delete(item.id);
            onChange([...pairs.entries()].flat());
          }}>
          <option value="">{labels.choose}</option>
          {right.map((choice) => (
            <option key={choice.id} value={choice.id} disabled={used.has(choice.id) && pairs.get(item.id) !== choice.id}>
              {choice.text}
            </option>
          ))}
        </select>
      </label>
    ))}
  </div>;
}

export function MatchingPairEditor({ choices, language, onEdit, onAdd, onRemove }: {
  choices: readonly { id?: string; text: string }[];
  language: string;
  onEdit: (index: number, value: string) => void;
  onAdd: () => void;
  onRemove: (index: number) => void;
}) {
  const labels = matchingCopy(language);
  return <div className="space-y-3">
    <p className="text-sm text-muted-foreground">{labels.authorHint}</p>
    {choices.filter((_, index) => index % 2 === 0).map((left, pairIndex) => {
      const index = pairIndex * 2;
      return <div key={left.id ?? index} className="grid min-w-0 gap-2 rounded-lg border p-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
        {[labels.left, labels.right].map((label, side) => (
          <label key={side} className="min-w-0 space-y-1 text-sm">
            <span>{label} {pairIndex + 1}</span>
            <Input value={choices[index + side]?.text ?? ''} onChange={(event) => onEdit(index + side, event.target.value)} />
          </label>
        ))}
        <Button type="button" variant="outline" size="sm" disabled={choices.length <= 4}
          aria-label={labels.remove + ' ' + (pairIndex + 1)} onClick={() => onRemove(index)}>{labels.remove}</Button>
      </div>;
    })}
    <Button type="button" variant="outline" size="sm" disabled={choices.length >= 50} onClick={onAdd}>{labels.add}</Button>
  </div>;
}
