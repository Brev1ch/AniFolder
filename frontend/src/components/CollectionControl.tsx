import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { useAuthStore } from '../store';
import { getMyList, updateListItem } from '../api/profile';
import { listKey, ListPatch } from '../api/demo';
import { Anime } from '../types/anime';
export const collectionStatuses = { watching: 'Смотрю', planned: 'В планах', completed: 'Просмотрено', on_hold: 'Отложено', dropped: 'Брошено' };
export const CollectionControl = ({ anime, compact = false }: { anime: Anime; compact?: boolean }) => {
  const { isAuthenticated, user } = useAuthStore();
  const cache = useQueryClient();
  const { data, isLoading, isError } = useQuery({ queryKey: listKey(), queryFn: getMyList, enabled: isAuthenticated });
  const item = data?.data.find(entry => entry.id === anime.id);
  const mutation = useMutation({ mutationFn: (patch: ListPatch) => updateListItem(anime.id, patch, anime), onSuccess: () => { cache.invalidateQueries({ queryKey: ['myList'] }); cache.invalidateQueries({ queryKey: ['recommendations'] }); } });
  if (!isAuthenticated) return <Link to="/login" className="button-secondary w-full text-center">Войти и сохранить</Link>;
  return <div key={user?.username} className="space-y-2">
    {item ? <label className="block"><span className="sr-only">Статус в списке</span><select className="field !py-2" value={item.status} disabled={mutation.isPending} onChange={event => mutation.mutate({ status: event.target.value as NonNullable<ListPatch['status']> })}>{Object.entries(collectionStatuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label> : <button className="button-primary w-full" disabled={mutation.isPending || isLoading || isError} onClick={() => mutation.mutate({ status: 'planned' })}>{mutation.isPending ? 'Сохраняем…' : '+ В планы'}</button>}
    {!compact && item && <div className="flex flex-wrap items-center gap-3"><span className="text-sm text-gray-400">{item.episodes_watched} / {item.episodes || '?'} серий</span><button className="button-secondary" disabled={mutation.isPending || (item.episodes !== null && item.episodes_watched >= item.episodes)} onClick={() => mutation.mutate({ episodes_watched: item.episodes_watched + 1 })}>+1 серия</button><label className="flex items-center gap-2 text-sm text-gray-400">Оценка<select className="field !w-auto !py-2" value={item.score ?? ''} disabled={mutation.isPending} onChange={event => mutation.mutate({ score: event.target.value ? Number(event.target.value) : null })}><option value="">—</option>{Array.from({ length: 10 }, (_, i) => <option key={i} value={i + 1}>{i + 1}</option>)}</select></label></div>}
    {(mutation.isError || isError) && <p role="alert" className="text-xs text-red-300">Не удалось обновить список. Попробуй ещё раз.</p>}
  </div>;
};
