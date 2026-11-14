import { getApiError } from './client';

type AuthField = 'username' | 'email' | 'password';
export type AuthErrors = Partial<Record<AuthField | 'form', string>> & { rateLimited?: boolean };

export function validateCredentials(username: string, password: string): AuthErrors {
  const errors: AuthErrors = {};
  if (!/^[A-Za-z0-9_]{3,32}$/.test(username)) {
    errors.username = 'Имя должно содержать от 3 до 32 латинских букв, цифр или знаков подчёркивания.';
  }
  const length = Array.from(password).length;
  if (length < 8 || length > 72) {
    errors.password = 'Пароль должен содержать от 8 до 72 символов.';
  } else if (new TextEncoder().encode(password).length > 72) {
    errors.password = 'Пароль должен занимать не более 72 байт в UTF-8.';
  }
  return errors;
}

export function readAuthErrors(error: unknown, fields: AuthField[], fallback: string): AuthErrors {
  const apiError = getApiError(error);
  const message = apiError?.message ?? fallback;

  switch (apiError?.code) {
    case 'RATE_LIMITED':
      return { rateLimited: true };
    case 'USERNAME_TAKEN':
      return { username: message };
    case 'EMAIL_TAKEN':
      return fields.includes('email') ? { email: message } : { form: message };
    case 'VALIDATION_ERROR': {
      const errors: AuthErrors = {};
      for (const detail of apiError.details ?? []) {
        const field = fields.find((name) => detail.loc[0] === 'body' && detail.loc[1] === name);
        if (field) errors[field] ??= detail.msg;
        else errors.form ??= detail.msg;
      }
      return Object.keys(errors).length ? errors : { form: message };
    }
    default:
      return { form: message };
  }
}
