import { useParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { getAnimeDetails, getAnimeReviews, createReview } from '../api/anime';
import { AnimePoster } from '../components/AnimePoster';
import { displayGenre, displayTitle } from '../types/anime';
import { CollectionControl } from '../components/CollectionControl';
import { useAuthStore } from '../store';

export const AnimeDetailsPage = () => {
  const { id } = useParams<{ id: string }>();
  const animeId = Number(id);
  const queryClient = useQueryClient();
  const { isAuthenticated } = useAuthStore();

  const [reviewText, setReviewText] = useState('');
  const [reviewScore, setReviewScore] = useState(10);

  const { data: animeData, isLoading: isLoadingAnime } = useQuery({
    queryKey: ['anime', animeId],
    queryFn: () => getAnimeDetails(animeId),
    enabled: !!animeId,
  });
  const anime = animeData?.data;

  const { data: reviewsData, isLoading: isLoadingReviews } = useQuery({
    queryKey: ['reviews', animeId],
    queryFn: () => getAnimeReviews(animeId),
    enabled: !!animeId,
  });
  const reviews = reviewsData?.data || [];

  const reviewMutation = useMutation({
    mutationFn: (data: { score: number; text: string }) => createReview(animeId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reviews', animeId] });
      setReviewText('');
      setReviewScore(10);
    },
  });

  const handleReviewSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!isAuthenticated) {
      alert('Пожалуйста, войдите в систему');
      return;
    }
    reviewMutation.mutate({ score: reviewScore, text: reviewText });
  };

  if (isLoadingAnime) {
    return <div className="text-center py-20 text-gray-400">Загрузка тайтла...</div>;
  }

  if (!anime) {
    return <div className="text-center py-20 text-red-400">Тайтл не найден</div>;
  }

  const title = displayTitle(anime);
  const avgScore = Number.parseFloat(anime.stats?.avg_score ?? '');
  const metadata = [
    anime.title_en !== title ? anime.title_en : null,
    anime.kind?.toUpperCase(),
    anime.aired_on?.slice(0, 4),
    anime.episodes === null ? null : `${anime.episodes} эп.`,
  ].filter(Boolean);

  return (
    <div className="max-w-5xl mx-auto rounded-lg shadow-lg overflow-hidden" style={{ backgroundColor: '#27222b' }}>
      <div className="md:flex">
        <div className="md:w-1/3">
          <AnimePoster anime={anime} className="w-full aspect-[2/3] object-cover" />
        </div>
        <div className="p-6 sm:p-9 md:w-2/3">
          <h1 className="text-3xl font-bold mb-2 text-white">{title}</h1>
          {metadata.length > 0 && <p className="text-gray-400 mb-4">{metadata.join(' · ')}</p>}
          {anime.genres.length > 0 && (
            <ul aria-label="Жанры" className="mb-4 flex flex-wrap gap-2">
              {anime.genres.map((genre) => <li key={genre.id} className="filter-chip">{displayGenre(genre)}</li>)}
            </ul>
          )}
          <p className="mb-6 text-gray-300 leading-relaxed whitespace-pre-line">
            {anime.description ?? 'Описание пока не добавлено.'}
          </p>

          <div className="mb-6 space-y-1 text-sm text-gray-400">
            <p>{Number.isFinite(avgScore) ? `Средняя оценка ${avgScore.toLocaleString('ru-RU', { maximumFractionDigits: 2 })} из 10` : 'Оценок пока нет'}</p>
            {anime.stats && (
              <p>Оценок {anime.stats.scores_count} · В списках {anime.stats.in_lists_count}</p>
            )}
          </div>

          <CollectionControl anime={anime} />
        </div>
      </div>

      <div className="p-6 border-t border-gray-800">
        <h2 className="text-2xl font-bold mb-4 text-white">
          Отзывы сообщества ({reviews.length})
        </h2>

        {isAuthenticated && (
          <form
            onSubmit={handleReviewSubmit}
            className="mb-8 p-4 rounded-lg border border-gray-800"
            style={{ backgroundColor: '#1c191f' }}
          >
            <h3 className="font-bold mb-2 text-gray-200">Оставить отзыв</h3>
            <textarea
              value={reviewText}
              onChange={(e) => setReviewText(e.target.value)}
              className="w-full border border-gray-700 bg-gray-900 text-white rounded p-2 mb-3 focus:ring-2 outline-none"
              rows={3}
              placeholder="Ваше мнение..."
              required
            />
            <div className="flex justify-between items-center">
              <div className="flex items-center gap-2">
                <label className="text-sm text-gray-400">Оценка:</label>
                <select
                  value={reviewScore}
                  onChange={(e) => setReviewScore(Number(e.target.value))}
                  className="border border-gray-700 bg-gray-900 text-white rounded p-1 focus:ring-2 outline-none"
                >
                  {[...Array(10)].map((_, i) => (
                    <option key={i + 1} value={i + 1}>
                      {i + 1}
                    </option>
                  ))}
                </select>
              </div>
              <button
                type="submit"
                disabled={reviewMutation.isPending || !reviewText}
                className="text-white px-4 py-2 rounded hover:opacity-90 disabled:opacity-50 transition-colors font-medium"
                style={{ backgroundColor: '#a884b5', color: '#211926' }}
              >
                {reviewMutation.isPending ? 'Отправка...' : 'Отправить'}
              </button>
            </div>
          </form>
        )}

        <div className="space-y-4">
          {isLoadingReviews ? (
            <div className="text-center py-10 text-gray-400">Загрузка отзывов...</div>
          ) : reviews.length === 0 ? (
            <div className="text-center py-10 text-gray-400">
              Отзывов пока нет. Будьте первым!
            </div>
          ) : (
            reviews.map((review) => (
              <div key={review.id} className="border-b border-gray-800 pb-4 last:border-0">
                <div className="flex justify-between items-center mb-2">
                  <span className="font-bold" style={{ color: '#a884b5' }}>{review.username}</span>
                  <span 
                    className="px-2 py-0.5 rounded text-sm font-bold border"
                    style={{ backgroundColor: '#a884b520', color: '#a884b5', borderColor: '#a884b540' }}
                  >
                    {review.score}/10
                  </span>
                </div>
                <p className="text-gray-300 text-sm whitespace-pre-line">{review.text}</p>
                <p className="text-xs text-gray-500 mt-2">
                  {new Date(review.created_at).toLocaleDateString()}
                </p>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};

