export interface Anime {
  id: number;
  anilist_id: number;
  mal_id: number | null;
  title_ru: string | null;
  title_en: string;
  kind: string | null;
  status: string;
  episodes: number | null;
  aired_on: string | null;
  poster_url: string | null;
}

export interface Genre {
  id: number;
  name_ru: string | null;
  name_en: string;
}

export interface AnimeDetail extends Anime {
  description: string | null;
  genres: Genre[];
  stats: {
    scores_count: number;
    avg_score: string | null;
    in_lists_count: number;
  } | null;
}

export const displayTitle = (anime: Anime) => anime.title_ru ?? anime.title_en;
export const displayGenre = (genre: Genre) => genre.name_ru ?? genre.name_en;

export interface AnimeListResponse {
  items: Anime[];
  total: number;
  page: number;
  limit: number;
}

export interface UserListAnime extends Anime {
  status: 'watching' | 'planned' | 'completed' | 'dropped' | 'on_hold';
  score: number | null;
  episodes_watched: number;
  updated_at: string;
}

export interface Recommendation {
  anime_id: number;
  relevance: number;
  anime: Anime;
}

export interface ActivityItem {
  id: number;
  type: 'added_to_list' | 'score_changed' | 'progress_updated' | 'review_created';
  anime_id: number;
  payload: {
    status?: string;
    score?: number;
    episodes_watched?: number;
    review_text?: string;
  };
  created_at: string;
  anime?: Anime;
}