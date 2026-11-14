import { authClient } from './client';

export interface LoginRequest {
  username: string;
  password: string;
}

export interface RegisterRequest {
  username: string;
  email: string;
  password: string;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: 'bearer';
  user: {
    id: number;
    username: string;
    email: string;
  };
}

export const loginApi = (data: LoginRequest): Promise<{ data: AuthResponse }> =>
  authClient.post<AuthResponse>('/auth/login', data);

export const registerApi = (data: RegisterRequest): Promise<{ data: AuthResponse }> =>
  authClient.post<AuthResponse>('/auth/register', data);
