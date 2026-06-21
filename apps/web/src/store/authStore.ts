import { create } from 'zustand';
import { AuthState, getStoredAuth, setStoredAuth, clearStoredAuth } from '@/lib/auth';

interface AuthStore extends AuthState {
  initialize: () => void;
  login: (accessToken: string, refreshToken: string, user: AuthState['user']) => void;
  logout: () => void;
  updateUser: (user: Partial<AuthState['user']>) => void;
}

export const useAuthStore = create<AuthStore>((set) => ({
  accessToken: null,
  refreshToken: null,
  user: null,

  initialize: () => {
    const auth = getStoredAuth();
    if (auth) {
      set(auth);
    }
  },

  login: (accessToken, refreshToken, user) => {
    set({ accessToken, refreshToken, user });
    setStoredAuth({ accessToken, refreshToken, user });
  },

  logout: () => {
    set({ accessToken: null, refreshToken: null, user: null });
    clearStoredAuth();
  },

  updateUser: (partial) => {
    set((state) => ({
      user: state.user ? { ...state.user, ...partial } : null,
    }));
  },
}));
