import { Anime, UserListAnime } from '../types/anime';
import { useAuthStore } from '../store';

// Local collection used until the list API is available.
export const listKey = () => ['myList', useAuthStore.getState().user?.username || 'guest'];
const storageKey = () => `anifolder:collection:v2:${useAuthStore.getState().user?.username || 'guest'}`;
export const readDemoList = (): UserListAnime[] => {
  const raw = localStorage.getItem(storageKey());
  if (raw) { try { const value = JSON.parse(raw); if (Array.isArray(value) && value.every(item => Number.isInteger(item.id) && typeof item.status === 'string' && Number.isFinite(item.episodes_watched))) return value; } catch { /* Reset invalid demo data. */ } }
  return [];
};
export type ListPatch = { status?: UserListAnime['status']; score?: number | null; episodes_watched?: number };
export const saveDemoItem = (id: number, patch: ListPatch, anime?: Anime) => {
  const list = readDemoList();
  const previous = list.find(item => item.id === id);
  const details = anime ?? previous;
  if (!details) throw new Error('Тайтл не найден');
  const item: UserListAnime = {
    ...details,
    status: patch.status ?? previous?.status ?? 'planned',
    episodes_watched: patch.episodes_watched ?? previous?.episodes_watched ?? 0,
    score: patch.score === undefined ? previous?.score ?? null : patch.score,
    updated_at: new Date().toISOString(),
  };
  item.episodes_watched = Math.max(0, Math.min(item.episodes ?? Infinity, Math.trunc(item.episodes_watched)));
  localStorage.setItem(storageKey(), JSON.stringify([...list.filter(entry => entry.id !== id), item]));
  return item;
};
export const deleteDemoItem = (id: number) => localStorage.setItem(storageKey(), JSON.stringify(readDemoList().filter(item => item.id !== id)));
