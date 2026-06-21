import { create } from 'zustand';
import { AuthUser, getStoredAuth, setStoredAuth, clearStoredAuth } from '@/lib/auth';

interface AuthStore {
  accessToken: string | null;
  user: AuthUser | null;
  initialize: () => void;
  login: (accessToken: string, user: AuthUser) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthStore>((set) => ({
  accessToken: null,
  user: null,

  initialize: () => {
    const auth = getStoredAuth();
    if (auth) {
      set({ accessToken: auth.access_token, user: auth.user });
    }
  },

  login: (accessToken, user) => {
    set({ accessToken, user });
    setStoredAuth({ access_token: accessToken, user });
  },

  logout: () => {
    set({ accessToken: null, user: null });
    clearStoredAuth();
  },
}));
