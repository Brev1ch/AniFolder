"""Веса взаимодействий для ALS: насколько запись «пользователь — тайтл» говорит об интересе.

вес = вес статуса × поправка за оценку × затухание по давности (по умолчанию выключено).

Решения EDA (ноутбук notebooks/01_eda.ipynb, разделы 3, 4 и 6):
- статусы: completed и watching — явный интерес, on_hold и planned — слабый,
  dropped — «не понравилось». В текущем варианте у брошенного вес 0:
  это наше решение, implicit ALS также поддерживает отрицательные сигналы;
- оценка уточняет вес относительно личной шкалы пользователя: у одного все
  тайтлы на 8–10, у другого 7 — уже высокая оценка. Оценки ниже 5 — как
  брошенное, вес 0;
- популярность смещается к новому сезону, поэтому можно включить затухание:
  запись, изменённая half_life_days дней назад, весит вдвое меньше свежей.

Записи с весом 0 не попадают в обучение, но остаются в списке пользователя:
рекомендации и так исключают всё, что у него в списке.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

DEFAULT_STATUS_WEIGHTS: dict[str, float] = {
    "completed": 1.0,
    "watching": 1.0,
    "on_hold": 0.5,
    "planned": 0.5,
    "dropped": 0.0,
}


def score_adjustment(
    df: pd.DataFrame,
    coef: float = 0.2,
    min_score: int = 5,
    min_user_scores: int = 5,
    clip: tuple[float, float] = (0.5, 1.5),
) -> np.ndarray:
    """Поправка за оценку для каждой записи.

    - нет оценки → 1;
    - оценка ниже min_score → 0;
    - иначе 1 + coef × (оценка − личное среднее), ограничено clip.

    Личное среднее — по всем оценкам пользователя (низкие тоже часть его
    шкалы). Если оценок меньше min_user_scores, среднее по ним ненадёжно,
    и берётся общее среднее по всем оценкам в df: так при обучении на train
    оно не подсматривает в тест.
    """
    if coef < 0:
        raise ValueError("coef должен быть неотрицательным")
    low, high = clip
    if not 0 < low <= 1 <= high:
        raise ValueError("clip должен быть (low, high) с 0 < low <= 1 <= high")

    score = df["score"].astype("Float64").to_numpy(dtype=float, na_value=np.nan)
    if np.isnan(score).all():
        return np.ones(len(df))
    by_user = pd.Series(score, index=df.index).groupby(df["user_id"])
    user_mean = by_user.transform("mean").to_numpy()
    user_count = by_user.transform("count").to_numpy()
    reference = np.where(user_count >= min_user_scores, user_mean, np.nanmean(score))

    adjustment = np.clip(1 + coef * (score - reference), low, high)
    adjustment = np.where(np.isnan(score), 1.0, adjustment)
    # сравнение с NaN даёт False, так что записи без оценки здесь не обнулятся
    return np.where(score < min_score, 0.0, adjustment)


def recency_decay(
    updated_at: pd.Series,
    half_life_days: float,
    now: pd.Timestamp | None = None,
    floor: float = 0.25,
) -> np.ndarray:
    """Множитель давности: 0.5 ** (возраст в днях / half_life_days), не меньше floor.

    now — момент «сейчас» (по умолчанию самая поздняя запись). Записи без
    updated_at считаются самыми старыми и получают floor: совсем их не
    обнуляем, это обычные старые просмотры (17% записей AniList).
    """
    if half_life_days <= 0:
        raise ValueError("half_life_days должен быть положительным")
    if not 0 < floor <= 1:
        raise ValueError("floor должен быть в (0, 1]")
    if now is None:
        now = updated_at.max()
    age_days = ((now - updated_at).dt.total_seconds() / 86400).clip(lower=0)
    decay = 0.5 ** (age_days.to_numpy(dtype=float, na_value=np.nan) / half_life_days)
    return np.where(np.isnan(decay), floor, np.maximum(decay, floor))


def interaction_weights(
    df: pd.DataFrame,
    status_weights: Mapping[str, float] = DEFAULT_STATUS_WEIGHTS,
    score_coef: float = 0.2,
    min_score: int = 5,
    min_user_scores: int = 5,
    clip: tuple[float, float] = (0.5, 1.5),
    half_life_days: float | None = None,
    now: pd.Timestamp | None = None,
    decay_floor: float = 0.25,
) -> pd.Series:
    """Вес каждой записи df (индекс тот же). Параметры — для сравнения вариантов на ALS."""
    if any(weight < 0 for weight in status_weights.values()):
        raise ValueError("веса статусов должны быть неотрицательными")
    status = df["status"].map(status_weights)
    unknown = status.isna()
    if unknown.any():
        raise ValueError(f"нет веса для статусов: {sorted(df.loc[unknown, 'status'].astype(str).unique())}")

    weight = status.to_numpy(dtype=float) * score_adjustment(df, score_coef, min_score, min_user_scores, clip)
    if half_life_days is not None:
        weight *= recency_decay(df["updated_at"], half_life_days, now, decay_floor)
    return pd.Series(weight, index=df.index, name="weight")


def weighted_interactions(df: pd.DataFrame, **params) -> pd.DataFrame:
    """Записи для обучения: df с колонкой weight, без записей с весом 0."""
    out = df.assign(weight=interaction_weights(df, **params))
    return out[out["weight"] > 0].reset_index(drop=True)
