import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { registerApi } from '../api/auth';
import { useAuthStore } from '../store';
import { type AuthErrors, readAuthErrors, validateCredentials } from '../api/authErrors';
import { AuthRateLimitToast } from '../components/AuthRateLimitToast';

export const RegisterPage = () => {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState<AuthErrors>({});

  const navigate = useNavigate();
  const login = useAuthStore((state) => state.login);

  const mutation = useMutation({
    mutationFn: registerApi,
    onSuccess: (data) => {
      login(data.data.user, data.data.access_token, data.data.refresh_token);
      navigate('/me');
    },
    onError: (error) => {
      setErrors(readAuthErrors(error, ['username','email','password'], 'Ошибка регистрации. Проверьте данные.'));
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const validationErrors = validateCredentials(username, password);
    setErrors(validationErrors);
    if (Object.keys(validationErrors).length) return;
    mutation.mutate({ username, email, password });
  };

  return (
    <div className="max-w-md mx-auto mt-10 p-6 rounded-lg shadow-lg" style={{ backgroundColor: '#27222b' }}>
      <h2 className="text-2xl font-bold mb-6 text-center" style={{ color: '#f1ebf2' }}>
        Регистрация в <span style={{ color: '#a884b5' }}>AniFolder</span>
      </h2>

      {errors.rateLimited && <AuthRateLimitToast onDismiss={() => setErrors({})} />}
      {errors.form && (
        <div role="alert" className="mb-4 p-3 rounded text-sm" style={{ backgroundColor: '#ef444420', color: '#ef4444', border: '1px solid #ef444440' }}>
          {errors.form}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="register-username" className="block text-sm font-medium mb-1" style={{ color: '#cbbfce' }}>Имя пользователя</label>
          <input
            type="text"
            id="register-username"
            aria-invalid={Boolean(errors.username)}
            aria-describedby={errors.username ? 'register-username-error' : undefined}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full p-2 border rounded focus:ring-2 outline-none"
            style={{ backgroundColor: '#1c191f', color: '#f1ebf2', borderColor: errors.username ? '#ef4444' : '#3d3442' }}
            required
          />
          {errors.username && <p id="register-username-error" role="alert" className="mt-1 text-sm text-red-300">{errors.username}</p>}
        </div>
        <div>
          <label htmlFor="register-email" className="block text-sm font-medium mb-1" style={{ color: '#cbbfce' }}>Email</label>
          <input
            type="email"
            id="register-email"
            aria-invalid={Boolean(errors.email)}
            aria-describedby={errors.email ? 'register-email-error' : undefined}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full p-2 border rounded focus:ring-2 outline-none"
            style={{ backgroundColor: '#1c191f', color: '#f1ebf2', borderColor: errors.email ? '#ef4444' : '#3d3442' }}
            required
          />
          {errors.email && <p id="register-email-error" role="alert" className="mt-1 text-sm text-red-300">{errors.email}</p>}
        </div>
        <div>
          <label htmlFor="register-password" className="block text-sm font-medium mb-1" style={{ color: '#cbbfce' }}>Пароль</label>
          <input
            type="password"
            id="register-password"
            aria-invalid={Boolean(errors.password)}
            aria-describedby={errors.password ? 'register-password-error' : undefined}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full p-2 border rounded focus:ring-2 outline-none"
            style={{ backgroundColor: '#1c191f', color: '#f1ebf2', borderColor: errors.password ? '#ef4444' : '#3d3442' }}
            required
          />
          {errors.password && <p id="register-password-error" role="alert" className="mt-1 text-sm text-red-300">{errors.password}</p>}
        </div>

        <button
          type="submit"
          disabled={mutation.isPending}
          className="w-full py-2 px-4 font-medium rounded hover:opacity-90 disabled:opacity-50 transition-colors"
          style={{ backgroundColor: '#a884b5', color: '#211926' }}
        >
          {mutation.isPending ? 'Регистрация...' : 'Зарегистрироваться'}
        </button>
      </form>

      <p className="mt-4 text-center text-sm" style={{ color: '#b9adbe' }}>
        Уже есть аккаунт?{' '}
        <Link to="/login" className="hover:underline" style={{ color: '#a884b5' }}>
          Войти
        </Link>
      </p>
    </div>
  );
};

