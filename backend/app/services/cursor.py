"""Курсорная пагинация: opaque base64url-курсор поверх (created_at, id).

Используется лентой активности и комментариями: порядок по паре
(created_at, id) детерминирован даже внутри равных таймстампов.
Клиент курсор не парсит; любая порча — 422, а не 500.
"""

import base64
import binascii
import json
from datetime import datetime

from app.core import errors


def encode_cursor(created_at: datetime, item_id: int) -> str:
    payload = json.dumps({"c": created_at.isoformat(), "i": item_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("ascii")).decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        raw = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii"))
        return datetime.fromisoformat(raw["c"]), int(raw["i"])
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, binascii.Error):
        raise errors.AppError(422, errors.VALIDATION_ERROR, "Невалидный курсор") from None
