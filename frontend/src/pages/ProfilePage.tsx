import { Link } from 'react-router-dom';
import { listKey } from '../api/demo';
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getMyList, updateListItem, removeFromList, ListUpdateRequest } from '../api/profile';
import { useAuthStore } from '../store';
import { Anime, UserListAnime, displayTitle } from '../types/anime';
import { AnimePoster } from '../components/AnimePoster';
import { RecommendationsBlock } from '../components/RecommendationsBlock';

const STATUS_TABS = [
  { id: 'watching', label: 'Смотрю', color: '#a884b5' },
  { id: 'planned', label: 'В планах', color: '#947a9e' },
  { id: 'completed', label: 'Просмотрено', color: '#829885' },
  { id: 'on_hold', label: 'Отложено', color: '#ab9873' },
  { id: 'dropped', label: 'Брошено', color: '#b07a7a' },
] as const;

type StatusType = typeof STATUS_TABS[number]['id'];

export const ProfilePage = () => {
  const { user, isAuthenticated } = useAuthStore();
  const [activeTab, setActiveTab] = useState<StatusType>('watching');
  const queryClient = useQueryClient();
  const [removed, setRemoved] = useState<UserListAnime | null>(null);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: listKey(),
    queryFn: getMyList,
    enabled: isAuthenticated,
  });

  const fullList = data?.data || [];

  const updateMutation = useMutation({
    mutationFn: ({ animeId, payload, anime }: { animeId: number; payload: ListUpdateRequest; anime?: Anime }) =>
      updateListItem(animeId, payload, anime),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['myList'] }); queryClient.invalidateQueries({ queryKey: ['recommendations'] }); },
  });

  const removeMutation = useMutation({
    mutationFn: (animeId: number) => removeFromList(animeId),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['myList'] }); queryClient.invalidateQueries({ queryKey: ['recommendations'] }); },
  });

  const filteredList = fullList.filter((item) => item.status === activeTab);

  const handleScoreChange = (animeId: number, score: number | null) =>
    updateMutation.mutate({ animeId, payload: { score } });

  const handleEpisodesChange = (animeId: number, episodes: number) =>
    updateMutation.mutate({ animeId, payload: { episodes_watched: episodes } });

  const handleStatusChange = (animeId: number, status: StatusType) => {
    updateMutation.mutate({ animeId, payload: { status } });
    setActiveTab(status);
  };

  const handleRemove = (animeId: number) => {
    const item = fullList.find(entry => entry.id === animeId);
    removeMutation.mutate(animeId, { onSuccess: () => setRemoved(item || null) });
  };

  if (!isAuthenticated) {
    return (
      <div className="text-center py-20 text-gray-400">
        <p className="text-lg">Пожалуйста, войдите в систему, чтобы увидеть свой профиль.</p>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto">
      <div className="mb-8 p-6 rounded-lg shadow-sm border border-gray-800" style={{ backgroundColor: '#27222b' }}>
        <h1 className="text-3xl font-bold text-white mb-2">Коллекция {user?.username}</h1>
        <p className="text-gray-400">
          В вашем списке <span className="font-bold" style={{ color: '#a884b5' }}>{fullList.length}</span> тайтлов
        </p>
      </div>

      <div className="mb-7 grid grid-cols-3 gap-3">{[
        ['Смотрю', fullList.filter(item => item.status === 'watching').length],
        ['Завершено', fullList.filter(item => item.status === 'completed').length],
        ['Серий', fullList.reduce((sum, item) => sum + item.episodes_watched, 0)],
      ].map(([label, count]) => <div key={label} className="rounded-xl border border-gray-800 p-4"><span className="text-2xl font-semibold text-accent-hover">{count}</span><p className="mt-1 text-xs text-gray-400">{label}</p></div>)}</div>
      {(updateMutation.isError || removeMutation.isError) && <p role="alert" className="mb-4 text-sm text-red-300">Не удалось сохранить изменение. Попробуй ещё раз.</p>}
      {removed && <div role="status" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-gray-800 p-4 text-sm"><span>«{displayTitle(removed)}» удалено из списка</span><button className="text-accent-hover" disabled={updateMutation.isPending} onClick={() => updateMutation.mutate({ animeId: removed.id, anime: removed, payload: { status: removed.status, episodes_watched: removed.episodes_watched, score: removed.score } }, { onSuccess: () => setRemoved(null) })}>Отменить удаление</button></div>}

      <div className="flex flex-wrap gap-2 mb-6 pb-4">
        {STATUS_TABS.map((tab) => {
          const count = fullList.filter((i) => i.status === tab.id).length;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className="px-4 py-2 rounded-lg font-medium transition-colors"
              style={{
                backgroundColor: activeTab === tab.id ? tab.color : '#1c191f',
                color: activeTab === tab.id ? '#211926' : '#b9adbe',
                border: activeTab === tab.id ? 'none' : '1px solid #3d3442',
              }}
            >
              {tab.label} <span className="ml-1 text-sm opacity-75">({count})</span>
            </button>
          );
        })}
      </div>

      {isError ? <div role="alert" className="py-10 text-center"><p>Не удалось загрузить коллекцию</p><button className="button-secondary mt-3" onClick={() => refetch()}>Повторить</button></div> : isLoading ? (
        <div className="text-center py-20 text-gray-400">Загрузка списков...</div>
      ) : filteredList.length === 0 ? (
        <div className="text-center py-20 rounded-lg border border-gray-800" style={{ backgroundColor: '#27222b' }}>
          <p className="text-lg text-gray-300">
            В категории «{STATUS_TABS.find((t) => t.id === activeTab)?.label}» пока пусто
          </p>
          <Link to="/catalog" className="button-secondary mt-4">Открыть каталог →</Link>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredList.map((item) => (
            <AnimeListItem
              key={item.id}
              item={item}
              onScoreChange={handleScoreChange}
              onEpisodesChange={handleEpisodesChange}
              onStatusChange={handleStatusChange}
              onRemove={handleRemove}
              isUpdating={updateMutation.isPending || removeMutation.isPending}
            />
          ))}
        </div>
      )}
      <div className="mt-12 border-t border-gray-800 pt-8"><RecommendationsBlock /></div>
    </div>
  );
};

interface AnimeListItemProps {
  item: UserListAnime;
  onScoreChange: (id: number, score: number | null) => void;
  onEpisodesChange: (id: number, episodes: number) => void;
  onStatusChange: (id: number, status: StatusType) => void;
  onRemove: (id: number) => void;
  isUpdating: boolean;
}

const AnimeListItem = ({ item, onScoreChange, onEpisodesChange, onStatusChange, onRemove, isUpdating }: AnimeListItemProps) => (
  <div className="p-4 rounded-lg shadow-sm border border-gray-800 flex gap-4 hover:shadow-md transition-shadow" style={{ backgroundColor: '#27222b' }}>
    <AnimePoster anime={item} className="w-20 h-28 object-cover rounded flex-shrink-0" />
    <div className="flex-grow min-w-0">
      <div className="flex justify-between items-start mb-2">
        <div>
          <Link to={`/anime/${item.id}`} className="font-semibold text-gray-100 hover:text-accent-hover">{displayTitle(item)}</Link>
          <p className="text-xs text-gray-400">
            {[item.kind?.toUpperCase(), item.episodes === null ? null : `${item.episodes} эп.`, item.aired_on?.slice(0, 4)].filter(Boolean).join(' · ')}
          </p>
        </div>
        <button
          aria-label={`Удалить ${displayTitle(item)} из списка`}
          onClick={() => onRemove(item.id)}
          disabled={isUpdating}
          className="text-red-400 hover:text-red-300 text-sm font-medium disabled:opacity-50"
        >
          ✕
        </button>
      </div>
      <div className="mb-3 mt-3"><progress aria-label={`Прогресс просмотра: ${displayTitle(item)}`} className="collection-progress" value={item.episodes_watched} max={item.episodes || Math.max(1, item.episodes_watched)} /><p className="mt-1 text-xs text-gray-400">Просмотрено {item.episodes_watched} из {item.episodes || '?'} серий</p></div>
      <div className="flex flex-wrap gap-4 items-center">
        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-400">Оценка:</label>
          <select
            aria-label={`Оценка: ${displayTitle(item)}`}
            value={item.score ?? ''}
            onChange={(e) => onScoreChange(item.id, e.target.value ? Number(e.target.value) : null)}
            disabled={isUpdating}
            className="border border-gray-700 rounded px-2 py-1 text-sm outline-none disabled:opacity-50 text-white"
            style={{ backgroundColor: '#1c191f' }}
          >
            <option value="">—</option>
            {[...Array(10)].map((_, i) => <option key={i + 1} value={i + 1}>{i + 1}</option>)}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-400">Эпизоды:</label>
          <input
            aria-label={`Просмотрено серий: ${displayTitle(item)}`}
            type="number"
            value={item.episodes_watched}
            onChange={(e) => onEpisodesChange(item.id, Math.min(Math.max(0, Number(e.target.value)), item.episodes || Infinity))}
            disabled={isUpdating}
            className="border border-gray-700 rounded px-2 py-1 w-16 text-sm outline-none disabled:opacity-50 text-white"
            style={{ backgroundColor: '#1c191f' }}
          />
          <button className="button-secondary !px-3 !py-1.5" disabled={isUpdating || (item.episodes !== null && item.episodes_watched >= item.episodes)} onClick={() => onEpisodesChange(item.id, item.episodes_watched + 1)}>+1 серия</button>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-400">Статус:</label>
          <select
            aria-label={`Статус: ${displayTitle(item)}`}
            value={item.status}
            onChange={(e) => onStatusChange(item.id, e.target.value as StatusType)}
            disabled={isUpdating}
            className="border border-gray-700 rounded px-2 py-1 text-sm outline-none disabled:opacity-50 text-white"
            style={{ backgroundColor: '#1c191f' }}
          >
            {STATUS_TABS.map((tab) => <option key={tab.id} value={tab.id}>{tab.label}</option>)}
          </select>
        </div>
      </div>
    </div>
  </div>
);

