export const AuthRateLimitToast = ({ onDismiss }: { onDismiss: () => void }) => (
  <div role="alert" className="fixed bottom-4 right-4 z-50 flex max-w-[calc(100%-2rem)] items-center gap-4 rounded-lg border border-red-400 bg-[var(--surface)] p-4 text-sm text-red-200 shadow-lg">
    <span>Слишком много попыток, подожди минуту</span>
    <button type="button" aria-label="Закрыть уведомление" onClick={onDismiss}>×</button>
  </div>
);
