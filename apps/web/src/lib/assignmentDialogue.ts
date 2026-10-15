const MAX_HISTORY_TURNS = 4;
const MAX_INSTRUCTION_CHARS = 2000;
const MAX_HISTORY_CHARS = 6000;

function isNonBlankString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

/**
 * Checks the bounded, user-only history accepted by assignment dialogue.
 * The predicate is deliberately runtime-safe because history can cross an
 * untrusted JSON boundary before it reaches the typed client code.
 */
export function isAssignmentDialogueHistory(
  value: unknown,
): value is string[] {
  if (!Array.isArray(value) || value.length > MAX_HISTORY_TURNS) {
    return false;
  }

  let totalChars = 0;
  for (const turn of value) {
    if (!isNonBlankString(turn) || turn.length > MAX_INSTRUCTION_CHARS) {
      return false;
    }

    totalChars += turn.length;
    if (totalChars > MAX_HISTORY_CHARS) {
      return false;
    }
  }

  return true;
}

/**
 * Returns a new history with one exact, nonblank user instruction appended.
 * Existing history and instruction text are never normalized or truncated.
 */
export function appendAssignmentInstruction(
  history: readonly string[],
  instruction: string,
): string[] {
  if (!isAssignmentDialogueHistory(history)) {
    throw new RangeError('Assignment dialogue history is outside its bounds');
  }

  if (!isNonBlankString(instruction)) {
    throw new RangeError('Assignment instruction must be nonblank');
  }

  if (instruction.length > MAX_INSTRUCTION_CHARS) {
    throw new RangeError('Assignment instruction exceeds 2000 characters');
  }

  const nextHistory = [...history, instruction];
  if (!isAssignmentDialogueHistory(nextHistory)) {
    throw new RangeError('Assignment dialogue history is outside its bounds');
  }

  return nextHistory;
}
