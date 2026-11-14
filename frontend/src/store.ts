import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface User {
  id: number;
  username: string;
  email: string;
}

interface AuthState {
  user: User | null;
  accessToken: string | null;
  refreshToken: string | null;
  isAuthenticated: boolean;
  sessionVersion: number;
  setTokens: (accessToken: string, refreshToken: string) => void;
  login: (user: User, accessToken: string, refreshToken: string) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
      sessionVersion: 0,
      setTokens: (accessToken, refreshToken) => set({ accessToken, refreshToken }),
      login: (user, accessToken, refreshToken) =>
        set((state) => ({ user, accessToken, refreshToken, isAuthenticated: true, sessionVersion: state.sessionVersion + 1 })),
      logout: () =>
        set((state) => ({ user: null, accessToken: null, refreshToken: null, isAuthenticated: false, sessionVersion: state.sessionVersion + 1 })),
    }),
    {
      name: 'auth-storage',
      onRehydrateStorage: () => (state) => {
        if (state?.accessToken === 'mock-access-token-123') state.logout();
      },
    }
  )
);