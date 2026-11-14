import { useState } from 'react';
import { Anime, displayTitle } from '../types/anime';

export const AnimePoster = ({ anime, className = '' }: { anime: Anime; className?: string }) => {
  const [failedPoster, setFailedPoster] = useState<string | null>(null);
  const url = anime.poster_url;
  const title = displayTitle(anime);

  if (url && url !== failedPoster && !url.includes('via.placeholder.com')) {
    return <img src={url} alt={title} loading="lazy" onError={() => setFailedPoster(url)} className={className} />;
  }

  return (
    <div role="img" aria-label="Постер отсутствует" className={`poster-placeholder grid place-items-center ${className}`}>
      <span className="text-4xl text-[#d9c5e2]/40" aria-hidden="true">{title.slice(0, 1)}</span>
    </div>
  );
};
