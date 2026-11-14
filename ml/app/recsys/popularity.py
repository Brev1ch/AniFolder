"""Рекомендации по популярности: baseline для сравнения с ALS и холодный старт.

- PopularityRecommender — «популярное за последние window_days дней». EDA
  (раздел 6) показал, что свежая популярность угадывает лучше популярности
  за всё время: пользователи переходят к новому сезону.
- GenrePopularityRecommender — то же, но тайтлы любимых жанров пользователя
  поднимаются выше. Нужен новичкам с 1–4 записями, которых ALS не видит
  из-за фильтра.

Интерфейс общий с будущими моделями: fit(interactions) → recommend(user, k)
и recommend_many(users, k) в формате, который принимает evaluate().
Из рекомендаций всегда исключается всё, что уже есть в списке пользователя,
включая брошенное.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from numbers import Integral

import numpy as np
import pandas as pd


def _validate_k(k: int) -> None:
    if isinstance(k, bool) or not isinstance(k, Integral) or k <= 0:
        raise ValueError("k должен быть положительным целым числом")


class PopularityRecommender:
    """Самое популярное за последние window_days дней (None — за всё время).

    Популярность тайтла — у скольких пользователей запись о нём появилась или
    изменилась за окно. Брошенное не считается: это сигнал «не понравилось».
    """

    def __init__(self, window_days: float | None = 28):
        if window_days is not None and window_days <= 0:
            raise ValueError("window_days должен быть положительным или None")
        self.window_days = window_days

    def fit(
        self, interactions: pd.DataFrame, now: pd.Timestamp | None = None,
        *, history: pd.DataFrame | None = None,
    ) -> PopularityRecommender:
        """now — момент «сейчас», по умолчанию самая поздняя запись.

        history — полная история для исключений, включая новичков и dropped;
        по умолчанию interactions. При офлайн-проверке передавайте только
        историю из train, без скрытых тестовых взаимодействий.
        """
        history = interactions if history is None else history
        self.seen_: dict[int, set[int]] = history.groupby("user_id")["anime_id"].agg(set).to_dict()
        counted = interactions[interactions["status"] != "dropped"]
        if self.window_days is not None:
            if now is None:
                now = interactions["updated_at"].max()
            # записи без updated_at в окно не попадают: когда их меняли, неизвестно;
            # записи позже now — будущее, их тоже не считаем
            start = now - pd.Timedelta(days=self.window_days)
            counted = counted[(counted["updated_at"] >= start) & (counted["updated_at"] <= now)]
        counts = counted["anime_id"].value_counts()
        # при равной популярности порядок по anime_id, чтобы выдача была воспроизводимой
        order = np.lexsort((counts.index.to_numpy(), -counts.to_numpy()))
        self.items_ = counts.index.to_numpy()[order]
        self.popularity_ = counts.to_numpy(dtype=float)[order]
        return self

    def _ranking(self, user_id: int) -> np.ndarray:
        return self.items_

    def recommend(self, user_id: int, k: int = 10) -> list[int]:
        """Топ-k без тайтлов из списка пользователя; k — положительное целое."""
        _validate_k(k)
        seen = self.seen_.get(user_id, set())
        recs: list[int] = []
        for item in self._ranking(user_id):
            if item not in seen:
                recs.append(int(item))
                if len(recs) == k:
                    break
        return recs

    def recommend_many(self, users: Iterable[int], k: int = 10) -> dict[int, list[int]]:
        _validate_k(k)
        return {user: self.recommend(user, k) for user in users}


class GenrePopularityRecommender(PopularityRecommender):
    """Свежее популярное с приоритетом любимых жанров пользователя.

    Любимые жанры — доля положительных записей пользователя (всё, кроме
    брошенного и оценок ниже min_score) с этим жанром; считаются только
    тайтлы, для которых жанры известны.

    счёт тайтла = популярность × (1 + beta × совпадение),
    совпадение — средняя доля жанров тайтла среди любимых (0 — если у тайтла
    жанров нет или ни один не любимый). Без любимых жанров — просто популярное.
    """

    def __init__(
        self,
        item_genres: Mapping[int, Iterable[int]] | Mapping[int, Iterable[str]],
        window_days: float | None = 28,
        beta: float = 1.0,
        min_score: int = 5,
    ):
        super().__init__(window_days)
        if beta < 0:
            raise ValueError("beta должен быть неотрицательным")
        self.item_genres = {item: set(genres) for item, genres in item_genres.items()}
        self.beta = beta
        self.min_score = min_score

    def fit(
        self, interactions: pd.DataFrame, now: pd.Timestamp | None = None,
        *, history: pd.DataFrame | None = None,
    ) -> GenrePopularityRecommender:
        """Популярность — по interactions, предпочтения и исключения — по history."""
        super().fit(interactions, now, history=history)
        history = interactions if history is None else history
        genres = sorted({g for gs in self.item_genres.values() for g in gs})
        column = {g: j for j, g in enumerate(genres)}

        # матрица «популярные тайтлы × жанры», строки нормированы: у тайтла
        # с жанрами {драма, романтика} по 0,5 на каждый — так получается среднее
        self.genre_matrix_ = np.zeros((len(self.items_), len(genres)))
        for i, item in enumerate(self.items_):
            item_genres = self.item_genres.get(item, ())
            for g in item_genres:
                self.genre_matrix_[i, column[g]] = 1 / len(item_genres)

        score = history["score"].astype("Float64")
        positive = (history["status"] != "dropped") & ~(score < self.min_score).fillna(False)
        known_genres = {item for item, genres in self.item_genres.items() if genres}
        liked = history.loc[positive & history["anime_id"].isin(known_genres), ["user_id", "anime_id"]]
        self.preferences_: dict[int, np.ndarray] = {}
        for user, items in liked.groupby("user_id")["anime_id"]:
            pref = np.zeros(len(genres))
            for item in items:
                for g in self.item_genres[item]:
                    pref[column[g]] += 1
            self.preferences_[user] = pref / len(items)
        return self

    def _ranking(self, user_id: int) -> np.ndarray:
        pref = self.preferences_.get(user_id)
        if pref is None or not pref.any():
            return self.items_
        match = self.genre_matrix_ @ pref
        scores = self.popularity_ * (1 + self.beta * match)
        # items_ уже упорядочены по (популярность, anime_id), stable-сортировка сохраняет этот порядок при равенстве
        return self.items_[np.argsort(-scores, kind="stable")]
