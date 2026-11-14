import { useState } from 'react';
import { useNavigate, Link, useSearchParams } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { loginApi } from '../api/auth';
import { useAuthStore } from '../store';
import { type AuthErrors, readAuthErrors, validateCredentials } from '../api/authErrors';
import { AuthRateLimitToast } from '../components/AuthRateLimitToast';

export const LoginPage = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState<AuthErrors>({});
  const [searchParams, setSearchParams] = useSearchParams();
  const sessionRevoked = searchParams.get('session') === 'revoked';

  const navigate = useNavigate();
  const login = useAuthStore((state) => state.login);

  const mutation = useMutation({
    mutationFn: loginApi,
    onSuccess: (data) => {
      login(data.data.user, data.data.access_token, data.data.refresh_token);
      navigate('/me');
    },
    onError: (error) => {
      setErrors(readAuthErrors(error, ['username','password'], 'Ошибка входа. Проверьте данные.'));
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const validationErrors = validateCredentials(username, password);
    setErrors(validationErrors);
    if (sessionRevoked) setSearchParams({}, { replace: true });
    if (Object.keys(validationErrors).length) return;
    mutation.mutate({ username, password });
  };

  return (
    <div className="max-w-md mx-auto mt-10 p-6 rounded-lg shadow-lg" style={{ backgroundColor: '#27222b' }}>
      <h2 className="text-2xl font-bold mb-6 text-center" style={{ color: '#f1ebf2' }}>
        Вход в <span style={{ color: '#a884b5' }}>AniFolder</span>
      </h2>

      {errors.rateLimited && <AuthRateLimitToast onDismiss={() => setErrors({})} />}
      {(errors.form || sessionRevoked) && (
        <div role="alert" className="mb-4 p-3 rounded text-sm" style={{ backgroundColor: '#ef444420', color: '#ef4444', border: '1px solid #ef444440' }}>
          {errors.form ?? 'Сессия отозвана, войдите заново'}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="login-username" className="block text-sm font-medium mb-1" style={{ color: '#cbbfce' }}>Имя пользователя</label>
          <input
            type="text"
            id="login-username"
            aria-invalid={Boolean(errors.username)}
            aria-describedby={errors.username ? 'login-username-error' : undefined}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full p-2 border rounded focus:ring-2 outline-none"
            style={{ backgroundColor: '#1c191f', color: '#f1ebf2', borderColor: errors.username ? '#ef4444' : '#3d3442' }}
            required
          />
          {errors.username && <p id="login-username-error" role="alert" className="mt-1 text-sm text-red-300">{errors.username}</p>}
        </div>
        <div>
          <label htmlFor="login-password" className="block text-sm font-medium mb-1" style={{ color: '#cbbfce' }}>Пароль</label>
          <input
            type="password"
            id="login-password"
            aria-invalid={Boolean(errors.password)}
            aria-describedby={errors.password ? 'login-password-error' : undefined}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full p-2 border rounded focus:ring-2 outline-none"
            style={{ backgroundColor: '#1c191f', color: '#f1ebf2', borderColor: errors.password ? '#ef4444' : '#3d3442' }}
            required
          />
          {errors.password && <p id="login-password-error" role="alert" className="mt-1 text-sm text-red-300">{errors.password}</p>}
        </div>

        <button
          type="submit"
          disabled={mutation.isPending}
          className="w-full py-2 px-4 font-medium rounded hover:opacity-90 disabled:opacity-50 transition-colors"
          style={{ backgroundColor: '#a884b5', color: '#211926' }}
        >
          {mutation.isPending ? 'Входим...' : 'Войти'}
        </button>
      </form>

      <p className="mt-4 text-center text-sm" style={{ color: '#b9adbe' }}>
        Нет аккаунта?{' '}
        <Link to="/register" className="hover:underline" style={{ color: '#a884b5' }}>
          Зарегистрироваться
        </Link>
      </p>
    </div>
  );
};

