import { apiClient } from './client';
import { AnimeListResponse, Genre } from '../types/anime';

interface GetAnimeParams {
  page?: number;
  limit?: number;
  search?: string;
  genre_id?: number;
  status?: string;
}

export const getAnimeList = (params: GetAnimeParams): Promise<{ data: AnimeListResponse }> =>
  apiClient.get<AnimeListResponse>('/anime', {
    params: { ...params, search: params.search?.trim() || undefined },
  });

export const getGenres = (): Promise<{ data: Genre[] }> =>
  apiClient.get<Genre[]>('/genres');
