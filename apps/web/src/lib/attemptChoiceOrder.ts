function hashSeed(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash = Math.imul(hash ^ value.charCodeAt(index), 16777619);
  }
  return hash >>> 0;
}

export function attemptChoiceOrder<T extends { id: string }>(
  choices: readonly T[],
  attemptScope: string,
  questionId: string,
  attemptIndex: number,
): readonly T[] {
  if (choices.length < 2) return choices;

  const scope = JSON.stringify([attemptScope, questionId]);
  const ordered = [...choices].sort((left, right) => left.id < right.id ? -1 : Number(left.id > right.id));
  const anchorIndex = hashSeed(scope) % ordered.length;
  const [anchor] = ordered.splice(anchorIndex, 1);

  let seed = hashSeed(JSON.stringify([scope, attemptIndex]));
  for (let index = ordered.length - 1; index > 0; index -= 1) {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    const next = Math.floor((seed / 0x100000000) * (index + 1));
    [ordered[index], ordered[next]] = [ordered[next], ordered[index]];
  }

  // Moving one stable choice guarantees a different order on every adjacent attempt.
  ordered.splice((anchorIndex + attemptIndex) % choices.length, 0, anchor);
  return ordered;
}
