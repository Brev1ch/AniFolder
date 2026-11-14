import axios, { CanceledError, type InternalAxiosRequestConfig } from 'axios';
import { useAuthStore } from '../store';
import type { AuthResponse } from './auth';

const options = {
  baseURL: import.meta.env.VITE_API_URL || '/api/v1',
  headers: { 'Content-Type': 'application/json' },
};

export const apiClient = axios.create(options);
export const authClient = axios.create(options);

interface AuthenticatedRequest extends InternalAxiosRequestConfig {
  sessionVersion?: number;
  retried?: boolean;
}

interface ApiErrorBody {
  error?: {
    code?: string;
    message?: string;
    details?: { loc: (string | number)[]; msg: string }[];
  };
}

export function getApiError(error: unknown) {
  return axios.isAxiosError<ApiErrorBody>(error) ? error.response?.data?.error : undefined;
}

let pendingRefresh: { token: string; promise: Promise<void> } | undefined;

function refreshSession(token: string, sessionVersion: number) {
  if (pendingRefresh?.token === token) return pendingRefresh.promise;

  const promise = authClient.post<AuthResponse>('/auth/refresh', { refresh_token: token })
    .then(({ data }) => {
      const state = useAuthStore.getState();
      if (state.sessionVersion === sessionVersion) {
        state.setTokens(data.access_token, data.refresh_token);
      }
    })
    .catch((error: unknown) => {
      const state = useAuthStore.getState();
      if (state.sessionVersion === sessionVersion) {
        const revoked = getApiError(error)?.code === 'REFRESH_TOKEN_REUSED';
        state.logout();
        window.location.replace(revoked ? '/login?session=revoked' : '/login');
      }
      throw error;
    })
    .finally(() => {
      if (pendingRefresh?.promise === promise) pendingRefresh = undefined;
    });

  pendingRefresh = { token, promise };
  return promise;
}

apiClient.interceptors.request.use((config: AuthenticatedRequest) => {
  const { accessToken, sessionVersion } = useAuthStore.getState();
  if (config.retried && config.sessionVersion !== sessionVersion) throw new CanceledError();

  config.sessionVersion = sessionVersion;
  if (accessToken) config.headers.set('Authorization', `Bearer ${accessToken}`);
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error: unknown) => {
    if (!axios.isAxiosError(error) || error.response?.status !== 401) throw error;

    const config: AuthenticatedRequest | undefined = error.config;
    const { accessToken, refreshToken, sessionVersion } = useAuthStore.getState();
    const sentAuthorization = config?.headers.get('Authorization');
    if (!config || config.retried || !sentAuthorization || !accessToken || !refreshToken ||
        config.sessionVersion !== sessionVersion) {
      throw error;
    }

    // A delayed 401 can arrive after another request has already rotated the token.
    if (sentAuthorization === `Bearer ${accessToken}`) {
      await refreshSession(refreshToken, sessionVersion);
    }

    config.retried = true;
    return apiClient.request(config);
  },
);
