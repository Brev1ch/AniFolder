import { Link } from 'react-router-dom';
import { useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { getAnimeList, getGenres } from '../api/catalog';
import { AnimeCard } from '../components/AnimeCard';
import { AnimePoster } from '../components/AnimePoster';
import { displayGenre, displayTitle } from '../types/anime';
import { useDebounce } from '../hooks/useDebounce';

const PAGE_SIZE = 12;
const statusLabels: Record<string, string> = { ongoing: 'Онгоинг', released: 'Завершён', announced: 'Анонс', hiatus: 'Приостановлен', cancelled: 'Отменён' };

export const CatalogPage = () => {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [selectedGenre, setSelectedGenre] = useState<number | undefined>();
  const [status, setStatus] = useState<string | undefined>();
  const debouncedSearch = useDebounce(search.trim(), 275);
  const { data, isLoading, isError, isFetching, isPlaceholderData, refetch } = useQuery({
    queryKey: ['anime', page, debouncedSearch, selectedGenre, status],
    queryFn: () => getAnimeList({ page, limit: PAGE_SIZE, search: debouncedSearch || undefined, genre_id: selectedGenre, status }),
    placeholderData: keepPreviousData,
    enabled: search.trim() === debouncedSearch,
  });
  const { data: genresData } = useQuery({ queryKey: ['genres'], queryFn: getGenres });
  const genres = genresData?.data || [];
  const animeList = data?.data.items || [];
  const total = data?.data.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const hasFilters = Boolean(search.trim() || selectedGenre || status);
  const activeGenre = genres.find((genre) => genre.id === selectedGenre);
  const resetFilters = () => { setSearch(''); setSelectedGenre(undefined); setStatus(undefined); setPage(1); };

  return (
    <section aria-labelledby="catalog-title">
      <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-[.18em] text-accent">Найди свою следующую историю</p>
          <h1 id="catalog-title" className="text-3xl font-semibold tracking-tight sm:text-4xl">Каталог аниме</h1>
          <p className="mt-3 max-w-xl text-sm leading-relaxed text-gray-400">Открывай новые миры и собирай то, что хочется посмотреть.</p>
        </div>
        {!isLoading && !isError && <span className="rounded-full border border-gray-800 px-3 py-1.5 text-xs text-gray-400">Тайтлов: <span className="font-medium text-gray-100">{total}</span></span>}
      </div>
      {!hasFilters && page === 1 && animeList[0] && <section aria-label="История для знакомства" className="mb-7 grid overflow-hidden rounded-2xl border border-gray-800 bg-[var(--surface)] sm:grid-cols-[1fr_200px]">
        <div className="p-6 sm:p-8"><p className="mb-3 text-xs uppercase tracking-[.18em] text-accent">Начни с новой истории</p><h2 className="text-2xl font-semibold">{displayTitle(animeList[0])}</h2><Link className="button-primary mt-5" to={`/anime/${animeList[0].id}`}>Подробнее о тайтле →</Link></div>
        <div className="hidden sm:block"><AnimePoster anime={animeList[0]} className="h-full max-h-72 min-h-40 w-full object-cover" /></div>
      </section>}
      <div className="mb-6 rounded-2xl border border-gray-800 bg-[var(--surface)] p-4 sm:p-5">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-[minmax(0,2fr)_1fr_1fr]">
          <div className="sm:col-span-2 lg:col-span-1">
            <label htmlFor="anime-search" className="filter-label">Название</label>
            <div className="relative">
              <svg className="pointer-events-none absolute left-3.5 top-3.5 text-gray-500" width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" stroke="currentColor" strokeWidth="1.8"/><path d="m16 16 4.5 4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>
              <input id="anime-search" type="search" placeholder="Какое аниме ищем?" value={search} maxLength={200} onChange={(event) => { setSearch(event.target.value); setPage(1); }} className="field !pl-11" />
            </div>
          </div>
          <div><label htmlFor="anime-genre" className="filter-label">Жанр</label><select id="anime-genre" value={selectedGenre ?? ''} onChange={(event) => { setSelectedGenre(event.target.value ? Number(event.target.value) : undefined); setPage(1); }} className="field"><option value="">Все жанры</option>{genres.map((genre) => <option key={genre.id} value={genre.id}>{displayGenre(genre)}</option>)}</select></div>
          <div><label htmlFor="anime-status" className="filter-label">Статус выхода</label><select id="anime-status" value={status || ''} onChange={(event) => { setStatus(event.target.value || undefined); setPage(1); }} className="field"><option value="">Любой статус</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
        </div>
        {hasFilters && <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-gray-800 pt-4">
          {search && <button className="filter-chip" onClick={() => { setSearch(''); setPage(1); }} aria-label="Убрать поиск по названию">«{search}» <span aria-hidden="true">×</span></button>}
          {selectedGenre && <button className="filter-chip" onClick={() => { setSelectedGenre(undefined); setPage(1); }} aria-label="Убрать фильтр по жанру">{activeGenre ? displayGenre(activeGenre) : 'Жанр'} <span aria-hidden="true">×</span></button>}
          {status && <button className="filter-chip" onClick={() => { setStatus(undefined); setPage(1); }} aria-label="Убрать фильтр по статусу">{statusLabels[status]} <span aria-hidden="true">×</span></button>}
          <button onClick={resetFilters} className="ml-auto rounded px-2 py-1 text-xs text-gray-400 hover:text-gray-100">Сбросить всё</button>
        </div>}
      </div>
      <div className="mb-5 flex min-h-5 items-center justify-between text-xs text-gray-500"><span>Выбирай, что посмотреть дальше</span><span role="status">{isFetching && !isLoading ? 'Обновляем…' : 'Твоя новая коллекция начинается здесь'}</span></div>
      {isError ? <div role="alert" className="rounded-2xl border border-gray-800 bg-[var(--surface)] px-6 py-16 text-center"><h2 className="text-lg font-semibold">Не удалось загрузить каталог</h2><p className="mb-5 mt-2 text-sm text-gray-400">Попробуй ещё раз через несколько секунд.</p><button className="button-secondary" onClick={() => refetch()}>Повторить</button></div> :
        <div aria-busy={isFetching}>
          {isLoading ? <div role="status"><span className="sr-only">Загрузка каталога</span><div className="grid grid-cols-2 gap-x-4 gap-y-7 sm:grid-cols-3 sm:gap-x-5 lg:grid-cols-4 xl:grid-cols-6">{Array.from({ length: PAGE_SIZE }, (_, index) => <div key={index} className="animate-pulse"><div className="aspect-[2/3] rounded-xl bg-[var(--surface)]" /><div className="mt-3 h-3 w-5/6 rounded bg-[var(--surface)]" /><div className="mt-3 h-2.5 w-1/2 rounded bg-[var(--surface)]" /></div>)}</div></div> : animeList.length ? <>
            <div className={`grid grid-cols-2 gap-x-4 gap-y-7 sm:grid-cols-3 sm:gap-x-5 lg:grid-cols-4 xl:grid-cols-6 ${isPlaceholderData ? 'opacity-60' : ''}`}>{animeList.map((anime) => <AnimeCard key={anime.id} anime={anime} />)}</div>
            <nav aria-label="Страницы каталога" className="mt-10 flex flex-wrap items-center justify-center gap-3 border-t border-gray-800 pt-7">
              <button className="button-secondary" disabled={page <= 1 || isPlaceholderData} onClick={() => setPage((value) => value - 1)}>← Назад</button>
              <span className="px-2 text-xs text-gray-400" aria-live="polite">{page} <span className="px-1 text-gray-600">/</span> {totalPages}</span>
              <button className="button-secondary" disabled={page >= totalPages || isPlaceholderData} onClick={() => setPage((value) => value + 1)}>Дальше →</button>
            </nav>
          </> : <div className="rounded-2xl border border-gray-800 bg-[var(--surface)] px-6 py-16 text-center"><h2 className="text-lg font-semibold">Пока ничего не нашлось</h2><p className="mb-5 mt-2 text-sm text-gray-400">Попробуй другое название или убери часть фильтров.</p>{hasFilters && <button className="button-secondary" onClick={resetFilters}>Сбросить фильтры</button>}</div>}
        </div>}
    </section>
  );
};
