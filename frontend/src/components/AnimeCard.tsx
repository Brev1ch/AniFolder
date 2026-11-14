import { CollectionControl } from './CollectionControl';
import { AnimePoster } from './AnimePoster';
import { Link } from 'react-router-dom';
import { Anime, displayTitle } from '../types/anime';

interface Props { anime: Anime; }
const statusLabels: Record<string, string> = { ongoing: 'Онгоинг', announced: 'Анонс', hiatus: 'Приостановлен', cancelled: 'Отменён' };

export const AnimeCard = ({ anime }: Props) => {
  const year = anime.aired_on ? new Date(anime.aired_on).getFullYear() : null;
  return (
    <article className="min-w-0"><Link to={`/anime/${anime.id}`} className="group block min-w-0 rounded-xl">
      <div className="poster-placeholder relative aspect-[2/3] overflow-hidden rounded-xl border border-white/5 transition-colors group-hover:border-[#a884b580]">
        <AnimePoster anime={anime} className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]" />
        {anime.kind && <span className="absolute left-2.5 top-2.5 rounded-md border border-white/10 bg-[#1c191f]/85 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-gray-100">{anime.kind}</span>}
        {statusLabels[anime.status] && <span className="absolute bottom-2.5 left-2.5 rounded-md bg-[#302436]/95 px-2 py-1 text-[10px] font-medium text-[#e2c9eb]">{statusLabels[anime.status]}</span>}
      </div>
      <div className="px-0.5 pb-2 pt-3">
        <h3 className="line-clamp-2 min-h-[2.75rem] text-sm font-semibold leading-[1.375rem] text-gray-100 transition-colors group-hover:text-accent-hover">{displayTitle(anime)}</h3>
        <p className="mt-1.5 text-xs text-gray-400">{year && Number.isFinite(year) ? year : 'Год неизвестен'}<span className="mx-1.5 text-gray-600">·</span>{anime.episodes ? `${anime.episodes} эп.` : 'Эпизоды уточняются'}</p>
      </div>
    </Link><CollectionControl anime={anime} compact /></article>
  );
};
