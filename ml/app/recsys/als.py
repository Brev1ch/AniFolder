"""CPU ALS с явными ID, полной историей исключений и сохранением артефакта.

fit принимает взаимодействия с колонкой weight (из weighted_interactions).
Confidence наблюдаемого интереса = 1 + alpha * weight, ненаблюдаемого = 1.
Неизвестному пользователю возвращается []; fallback выбирает вызывающий код.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from numbers import Integral
from pathlib import Path

import numpy as np
import pandas as pd
from implicit.cpu.als import AlternatingLeastSquares
from scipy.sparse import csr_matrix


class ALSRecommender:
    def __init__(self, factors: int = 64, regularization: float = 0.1,
                 alpha: float = 20.0, iterations: int = 20,
                 random_state: int = 42, num_threads: int = 1):
        for name, value in {"factors": factors, "iterations": iterations, "num_threads": num_threads}.items():
            if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
                raise ValueError(f"{name} должен быть положительным целым")
        if not np.isfinite(alpha) or alpha <= 0:
            raise ValueError("alpha должен быть положительным и конечным")
        if not np.isfinite(regularization) or regularization <= 0:
            raise ValueError("regularization должен быть положительным и конечным")
        self.params = dict(factors=factors, regularization=regularization, alpha=alpha,
                           iterations=iterations, random_state=random_state, num_threads=num_threads)

    def fit(self, interactions: pd.DataFrame, *, history: pd.DataFrame) -> ALSRecommender:
        """Обучает только по weight; history задаёт исключения, без validation/test.

        Нулевые веса не обучаются. Дубли (user_id, anime_id) запрещены.
        ID должны быть целыми, отрицательные внешние user_id поддерживаются.
        """
        for frame in (interactions, history):
            for column in ("user_id", "anime_id"):
                if frame[column].isna().any() or not pd.api.types.is_integer_dtype(frame[column]):
                    raise ValueError(f"{column} должен содержать целые ID без пропусков")
        if interactions.duplicated(["user_id", "anime_id"]).any():
            raise ValueError("повторяющиеся взаимодействия")
        weights = interactions["weight"].to_numpy(dtype=float, na_value=np.nan)
        if not np.isfinite(weights).all() or (weights < 0).any():
            raise ValueError("weight должен быть конечным и неотрицательным")
        positive = interactions.loc[weights > 0]
        if positive.empty:
            raise ValueError("нет положительных взаимодействий для ALS")
        self.user_ids_ = np.sort(positive.user_id.unique()).astype(np.int64)
        self.item_ids_ = np.sort(positive.anime_id.unique()).astype(np.int64)
        self.user_index_ = {int(u): i for i, u in enumerate(self.user_ids_)}
        item_index = {int(a): i for i, a in enumerate(self.item_ids_)}
        rows = positive.user_id.map(self.user_index_).to_numpy()
        cols = positive.anime_id.map(item_index).to_numpy()
        confidence = 1 + self.params["alpha"] * weights[weights > 0]
        shape = (len(self.user_ids_), len(self.item_ids_))
        matrix = csr_matrix((confidence.astype(np.float32), (rows, cols)), shape=shape)
        # alpha уже включена в matrix; библиотека не должна умножать её повторно.
        model = AlternatingLeastSquares(**{**self.params, "alpha": 1.0})
        model.fit(matrix, show_progress=False)
        self.user_factors_ = model.user_factors
        self.item_factors_ = model.item_factors
        if not np.isfinite(self.user_factors_).all() or not np.isfinite(self.item_factors_).all():
            raise RuntimeError("ALS вернул нечисловые факторы")

        # Включаем обучение даже при ошибочно неполной history. Брошенное и
        # низкие оценки берём из history, а не из разреженной матрицы интереса.
        seen = pd.concat([history[["user_id", "anime_id"]], positive[["user_id", "anime_id"]]])
        seen_rows = seen.user_id.map(self.user_index_)
        seen_cols = seen.anime_id.map(item_index)
        valid = seen_rows.notna() & seen_cols.notna()
        self.seen_ = csr_matrix((np.ones(valid.sum(), dtype=np.float32),
                                (seen_rows[valid].astype(int), seen_cols[valid].astype(int))), shape=shape)
        self.seen_.data.fill(1)
        self.metadata_ = {}
        return self

    @staticmethod
    def _validate_k(k: int) -> None:
        if isinstance(k, bool) or not isinstance(k, Integral) or k <= 0:
            raise ValueError("k должен быть положительным целым")

    def recommend(self, user_id: int, k: int = 10) -> list[int]:
        """Топ-k известных модели тайтлов; ничьи разрешаются по anime_id."""
        self._validate_k(k)
        if not hasattr(self, "user_index_"):
            raise RuntimeError("сначала обучите или загрузите ALS")
        row = self.user_index_.get(user_id)
        if row is None:
            return []
        scores = self.item_factors_ @ self.user_factors_[row]
        scores[self.seen_.indices[self.seen_.indptr[row]:self.seen_.indptr[row + 1]]] = -np.inf
        candidates = np.flatnonzero(np.isfinite(scores))
        order = np.lexsort((self.item_ids_[candidates], -scores[candidates]))
        return self.item_ids_[candidates[order[:k]]].tolist()

    def recommend_many(self, users: Iterable[int], k: int = 10) -> dict[int, list[int]]:
        self._validate_k(k)
        return {u: self.recommend(u, k) for u in users}

    def save(self, path: Path, *, metadata: dict | None = None) -> None:
        """Один атомарный NPZ: факторы, ID, исключения, параметры и контекст опыта.

        metadata предназначена для даты отсечения и настроек весов. Артефакт
        сохраняет выдачу снимка; обновление истории при serving — отдельный этап.
        """
        if not hasattr(self, "seen_"):
            raise RuntimeError("сначала обучите или загрузите ALS")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("wb") as out:
            np.savez_compressed(out, version=1, params=json.dumps(self.params),
                                metadata=json.dumps(self.metadata_ if metadata is None else metadata),
                                user_ids=self.user_ids_, item_ids=self.item_ids_,
                                user_factors=self.user_factors_, item_factors=self.item_factors_,
                                seen_indices=self.seen_.indices, seen_indptr=self.seen_.indptr)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Path) -> ALSRecommender:
        """Загрузка без pickle и переобучения, с исходными отображениями ID."""
        with np.load(path, allow_pickle=False) as data:
            if int(data["version"]) != 1:
                raise ValueError("неизвестная версия артефакта ALS")
            result = cls(**json.loads(str(data["params"])))
            result.metadata_ = json.loads(str(data["metadata"]))
            result.user_ids_, result.item_ids_ = data["user_ids"], data["item_ids"]
            result.user_index_ = {int(u): i for i, u in enumerate(result.user_ids_)}
            result.user_factors_, result.item_factors_ = data["user_factors"], data["item_factors"]
            result.seen_ = csr_matrix((np.ones(len(data["seen_indices"]), dtype=np.float32),
                                       data["seen_indices"], data["seen_indptr"]),
                                      shape=(len(result.user_ids_), len(result.item_ids_)))
        return result
