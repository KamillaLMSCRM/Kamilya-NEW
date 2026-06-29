import { create } from 'zustand';
import {
  AuthUser,
  getAccessToken,
  getCurrentUser,
  setAuth as setAuthMemory,
  clearAuth as clearAuthMemory,
  restoreSession,
  logout as logoutRequest,
  subscribeAuth,
} from '@/lib/auth';

interface AuthStore {
  accessToken: string | null;
  user: AuthUser | null;
  /** True once we've attempted to restore the session from the refresh cookie. */
  initialized: boolean;
  /** Initialize from the refresh cookie (call once on app mount). */
  initialize: () => Promise<void>;
  /** Set access token + user (called after successful login). */
  login: (accessToken: string, user: AuthUser) => void;
  /** Logout — clears in-memory state and tells server to blacklist the refresh cookie. */
  logout: () => Promise<void>;
  /** Manually set user (e.g. after profile update). */
  setUser: (user: AuthUser) => void;
}

// Initial state mirrors in-memory store (so SSR + first paint show correct state).
const initialState = {
  accessToken: typeof window === 'undefined' ? null : getAccessToken(),
  user: typeof window === 'undefined' ? null : getCurrentUser(),
  initialized: false,
};

export const useAuthStore = create<AuthStore>((set) => {
  // Subscribe to in-memory auth changes so the Zustand store stays in sync
  // with anything that calls setAuth/clearAuth directly (e.g. refresh logic).
  subscribeAuth(({ accessToken, user }) => {
    set({ accessToken, user });
  });

  return {
    ...initialState,

    initialize: async () => {
      if (get().initialized) return;
      await restoreSession();
      set({
        accessToken: getAccessToken(),
        user: getCurrentUser(),
        initialized: true,
      });
    },

    login: (accessToken, user) => {
      setAuthMemory(accessToken, user);
      // Force-initialize the store so any Layout/guard useEffects that
      // wait for `initialized === true` unblock immediately after a
      // successful login, instead of racing against the in-flight
      // /auth/refresh call inside initialize().
      set({ accessToken, user, initialized: true });
    },

    logout: async () => {
      await logoutRequest();
      clearAuthMemory();
      set({ accessToken: null, user: null });
    },

    setUser: (user) => {
      set({ user });
      // Also update the underlying memory store so getCurrentUser() is consistent.
      const token = getAccessToken();
      if (token) {
        setAuthMemory(token, user);
      }
    },
  };
});

// Helper for components that need to call get() without subscribing.
function get() {
  return useAuthStore.getState();
}