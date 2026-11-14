import { apiClient } from './client';
import { saveDemoItem } from './demo';
import { AnimeDetail } from '../types/anime';

const USE_MOCK = true;

export interface Review {
  id: number;
  user_id: number;
  username: string;
  score: number;
  text: string;
  created_at: string;
}

export interface ReviewCreateRequest {
  score: number;
  text: string;
}

export interface ListUpdateRequest {
  status: 'watching' | 'planned' | 'completed' | 'dropped' | 'on_hold';
  score?: number;
  episodes_watched?: number;
}

export const getAnimeDetails = (id: number): Promise<{ data: AnimeDetail }> =>
  apiClient.get<AnimeDetail>(`/anime/${id}`);

export const getAnimeReviews = async (id: number): Promise<{ data: Review[] }> => {
  if (USE_MOCK) {
    await new Promise((r) => setTimeout(r, 200));
    return {
      data: [
        { id: 1, user_id: 1, username: 'TestUser', score: 9, text: 'Отличное аниме! Мок-отзыв.', created_at: new Date().toISOString() },
        { id: 2, user_id: 2, username: 'AnimeFan', score: 7, text: 'Неплохо, но концовка смазана.', created_at: new Date().toISOString() },
      ],
    };
  }
  return apiClient.get<Review[]>(`/anime/${id}/reviews`);
};

export const createReview = async (id: number, data: ReviewCreateRequest): Promise<{ data: Review }> => {
  if (USE_MOCK) {
    await new Promise((r) => setTimeout(r, 300));
    return {
      data: { id: Date.now(), user_id: 1, username: 'Me', score: data.score, text: data.text, created_at: new Date().toISOString() },
    };
  }
  return apiClient.post<Review>(`/anime/${id}/reviews`, data);
};

export const updateMyList = async (animeId: number, data: ListUpdateRequest): Promise<{ data: any }> => {
  if (USE_MOCK) {
    await new Promise((r) => setTimeout(r, 300));
    return { data: saveDemoItem(animeId, data, (await getAnimeDetails(animeId)).data) };
  }
  return apiClient.put(`/me/list/${animeId}`, data);
};