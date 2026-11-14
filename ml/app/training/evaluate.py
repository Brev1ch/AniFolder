"""Оценка качества рекомендаций: holdout по времени и метрики top-k.

Схема проверки:
0. chronological_split: фиксированные границы train/validation/test без
   фильтрации пользователей и тайтлов. Параметры выбираются на validation,
   test используется после выбора. Фильтр редких применяется только к train;
   полная история train сохраняется для исключений и холодного старта.
1. Деление на train и test по времени:
   - cutoff_split (основная проверка): общая дата отсечения для всех,
     в тест уходят последние days дней. Модель не видит будущего других
     пользователей, как в реальной работе: обучили сегодня — рекомендуем
     на следующие недели;
   - time_split (вторая проверка): у каждого пользователя последние
     по updated_at записи уходят в тест.
   Цифры разных схем между собой не сравниваются, сравниваются модели
   внутри одной схемы.
2. relevant_items: какие тестовые тайтлы считаются удачной рекомендацией.
3. evaluate: модель выдаёт топ-k для каждого пользователя, считаем
   precision@k, recall@k, NDCG@k, усредняем по пользователям, и покрытие —
   сколько разных тайтлов модель вообще рекомендует.

updated_at — время последнего изменения записи, а не добавления: если
пользователь поправил оценку старому тайтлу, тот попадёт в тест. Такое
разбиение снимка списков не восстанавливает историю просмотров, а записи
без даты условно считаются старыми. Это ограничение офлайн-оценки.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from numbers import Integral

import pandas as pd


def chronological_split(
    df: pd.DataFrame,
    *,
    validation_start: pd.Timestamp,
    test_start: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Три непересекающихся периода с явно заданными границами с часовым поясом.

    train: дата < validation_start или NaT; validation: [validation_start,
    test_start); test: дата >= test_start. Ни одна запись не удаляется.
    Границы задаются явно, чтобы фильтрация и новые данные не сдвигали их.
    Входной updated_at должен быть datetime с часовым поясом.

    Не фильтруйте df перед разбиением. Группы пользователей для оценки
    определяются по полной предшествующей истории, независимо от фильтра
    обучения; неизвестные модели тайтлы в validation/test сохраняются.
    """
    validation_start, test_start = pd.Timestamp(validation_start), pd.Timestamp(test_start)
    if any(pd.isna(t) or t.tzinfo is None for t in (validation_start, test_start)):
        raise ValueError("границы должны иметь часовой пояс и не быть NaT")
    if validation_start >= test_start:
        raise ValueError("validation_start должен быть раньше test_start")
    dates = df["updated_at"]
    if not isinstance(dates.dtype, pd.DatetimeTZDtype):
        raise ValueError("updated_at должен быть datetime с часовым поясом")
    train = dates.isna() | (dates < validation_start)
    validation = (dates >= validation_start) & (dates < test_start)
    test = dates >= test_start
    return tuple(df[mask].reset_index(drop=True) for mask in (train, validation, test))


def time_split(df: pd.DataFrame, test_fraction: float = 0.2) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Делит взаимодействия на train и test по времени внутри каждого пользователя.

    В тест уходят до floor(n * test_fraction) последних записей пользователя,
    где n — общее число его записей. Если записей с известной датой меньше,
    тест уменьшается; без известных дат пользователь целиком остаётся в train.
    При равном updated_at порядок задаёт anime_id, чтобы деление было
    воспроизводимым. Записи без updated_at (у AniList это 17%, видимо
    старые) считаются самыми ранними и всегда остаются в train.
    """
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction должен быть в (0, 1)")
    ordered = df.sort_values(["user_id", "updated_at", "anime_id"], na_position="first")
    from_end = ordered.groupby("user_id").cumcount(ascending=False)
    # 1e-9 против ошибок округления: 0.29 * 100 = 28.999…, а должно быть 29
    n_test = (ordered["user_id"].map(ordered["user_id"].value_counts()) * test_fraction + 1e-9) // 1
    is_test = (from_end < n_test) & ordered["updated_at"].notna()
    return ordered[~is_test].reset_index(drop=True), ordered[is_test].reset_index(drop=True)


def default_cutoff(df: pd.DataFrame, days: int = 28) -> pd.Timestamp:
    """Дата отсечения: days дней до самой поздней записи в данных."""
    if days <= 0:
        raise ValueError("days должен быть положительным")
    last = df["updated_at"].max()
    if pd.isna(last):
        raise ValueError("ни у одной записи нет updated_at")
    return last - pd.Timedelta(days=days)


def cutoff_split(
    df: pd.DataFrame,
    days: int = 28,
    min_train: int = 5,
    cutoff: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Делит взаимодействия по общей дате отсечения.

    train — все записи до cutoff (по умолчанию default_cutoff(df, days)),
    включая пользователей, которые в проверку не попадут: их записи
    помогают модели. Записи без updated_at считаются старыми и идут в train.

    test — записи начиная с cutoff, но только у пользователей, у которых
    в train не меньше min_train записей: по меньшему числу вкус не понять.
    Остальные записи после cutoff выбрасываются: в train они дали бы модели
    заглянуть в будущее.
    """
    if min_train < 1:
        raise ValueError("min_train должен быть не меньше 1")
    if cutoff is None:
        cutoff = default_cutoff(df, days)
    after = (df["updated_at"] >= cutoff).fillna(False).astype(bool)
    train = df[~after]
    train_counts = train["user_id"].value_counts()
    known = train_counts.index[train_counts >= min_train]
    test = df[after & df["user_id"].isin(known)]
    return train.reset_index(drop=True), test.reset_index(drop=True)


def relevant_items(test: pd.DataFrame, min_score: int = 5) -> dict[int, set[int]]:
    """Тестовые тайтлы, которые было бы правильно порекомендовать.

    Не считаются: брошенные (dropped) и с оценкой ниже min_score.
    planned считается: пользователь сам решил, что хочет это посмотреть.
    """
    good = (test["status"] != "dropped") & (test["score"].isna() | (test["score"] >= min_score))
    good = good.fillna(False).astype(bool)
    return test[good].groupby("user_id")["anime_id"].agg(set).to_dict()


def _validate_k(k: int) -> None:
    if isinstance(k, bool) or not isinstance(k, Integral) or k <= 0:
        raise ValueError("k должен быть положительным целым числом")


def _validated_top_k(recommended: Sequence[int], k: int) -> Sequence[int]:
    _validate_k(k)
    top = recommended[:k]
    if len(set(top)) != len(top):
        raise ValueError("повторяющиеся тайтлы в top-k рекомендациях")
    return top


def precision_at_k(recommended: Sequence[int], relevant: set[int], k: int) -> float:
    """Доля попаданий среди первых k рекомендаций."""
    hits = sum(item in relevant for item in _validated_top_k(recommended, k))
    return hits / k


def recall_at_k(recommended: Sequence[int], relevant: set[int], k: int) -> float:
    """Доля релевантных тайтлов, найденных в первых k рекомендациях."""
    top = _validated_top_k(recommended, k)
    if not relevant:
        return 0.0
    hits = sum(item in relevant for item in top)
    return hits / len(relevant)


def ndcg_at_k(recommended: Sequence[int], relevant: set[int], k: int) -> float:
    """NDCG@k с бинарной релевантностью: попадание выше в списке ценится больше.

    DCG = сумма 1 / log2(позиция + 1) по попаданиям; делим на DCG идеального
    списка, где все min(k, |relevant|) попаданий стоят в начале.
    """
    top = _validated_top_k(recommended, k)
    dcg = sum(1 / math.log2(pos + 2) for pos, item in enumerate(top) if item in relevant)
    ideal = sum(1 / math.log2(pos + 2) for pos in range(min(k, len(relevant))))
    return dcg / ideal if ideal else 0.0


def evaluate(
    recommendations: Mapping[int, Sequence[int]],
    relevant: Mapping[int, set[int]],
    k: int = 10,
) -> dict[str, float]:
    """Средние метрики по пользователям, у которых есть релевантные тайтлы в тесте.

    Пользователь без рекомендаций получает нули: модель, которая молчит,
    не должна выглядеть лучше.

    coverage@k — число разных тайтлов в топ-k у этих пользователей. Высокий
    NDCG при покрытии в десятки тайтлов значит «всем советуем одно и то же».

    k должен быть положительным целым. Повторы в оцениваемом топ-k — ошибка
    выдачи (ValueError), а не дополнительные попадания. За пределами k
    рекомендации не проверяются и не учитываются.
    """
    _validate_k(k)
    users = [user for user, items in relevant.items() if items]
    if not users:
        raise ValueError("нет пользователей с релевантными тайтлами в тесте")
    totals = {f"precision@{k}": 0.0, f"recall@{k}": 0.0, f"ndcg@{k}": 0.0}
    shown: set[int] = set()
    for user in users:
        recs = recommendations.get(user, [])
        shown.update(recs[:k])
        totals[f"precision@{k}"] += precision_at_k(recs, relevant[user], k)
        totals[f"recall@{k}"] += recall_at_k(recs, relevant[user], k)
        totals[f"ndcg@{k}"] += ndcg_at_k(recs, relevant[user], k)
    result = {name: value / len(users) for name, value in totals.items()}
    result[f"coverage@{k}"] = len(shown)
    result["users"] = len(users)
    return result
