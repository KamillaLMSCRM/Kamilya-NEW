import { useCallback, useReducer } from 'react';

type Draft = {
  value: string;
  past: string[];
  future: string[];
  typing: boolean;
};

type Action =
  | { type: 'edit'; value: string; typing: boolean }
  | { type: 'reset' | 'saved'; value: string }
  | { type: 'endEdit' | 'undo' | 'redo' };

const undoLimit = 50;

function emptyHistory(value: string): Draft {
  return { value, past: [], future: [], typing: false };
}

function updateDraft(draft: Draft, action: Action): Draft {
  switch (action.type) {
    case 'reset':
      return emptyHistory(action.value);
    case 'saved':
      // A later local input must survive an earlier save response.
      return draft.value === action.value
        ? emptyHistory(action.value)
        : { ...emptyHistory(draft.value), past: [action.value] };
    case 'edit':
      if (action.value === draft.value) return draft;
      return {
        value: action.value,
        past: action.typing && draft.typing ? draft.past : [...draft.past.slice(1 - undoLimit), draft.value],
        future: [],
        typing: action.typing,
      };
    case 'endEdit':
      return draft.typing ? { ...draft, typing: false } : draft;
    case 'undo': {
      const value = draft.past.at(-1);
      if (value === undefined) return draft;
      return { value, past: draft.past.slice(0, -1), future: [draft.value, ...draft.future], typing: false };
    }
    case 'redo': {
      const [value, ...future] = draft.future;
      if (value === undefined) return draft;
      return { value, past: [...draft.past, draft.value], future, typing: false };
    }
  }
}

export function useLessonDraftHistory(initialValue: string) {
  const [draft, dispatch] = useReducer(updateDraft, initialValue, emptyHistory);
  const reset = useCallback((value: string) => dispatch({ type: 'reset', value }), []);
  return {
    value: draft.value,
    canUndo: draft.past.length > 0,
    canRedo: draft.future.length > 0,
    reset,
    saved: (value: string) => dispatch({ type: 'saved', value }),
    edit: (value: string, typing = false) => dispatch({ type: 'edit', value, typing }),
    endEdit: () => dispatch({ type: 'endEdit' }),
    undo: () => dispatch({ type: 'undo' }),
    redo: () => dispatch({ type: 'redo' }),
  };
}
