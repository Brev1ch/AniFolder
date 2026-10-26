import enum

from sqlalchemy import Enum


class ListStatus(str, enum.Enum):
    PLANNED = "planned"
    WATCHING = "watching"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"
    DROPPED = "dropped"


class ActivityType(str, enum.Enum):
    LIST_ADDED = "list_added"
    STATUS_CHANGED = "status_changed"
    PROGRESS_UPDATED = "progress_updated"
    SCORED = "scored"
    REVIEWED = "reviewed"
    TOPIC_CREATED = "topic_created"
    COMMENTED = "commented"


def _values(e: type[enum.Enum]) -> list[str]:
    return [m.value for m in e]


# create_type=False: типы создаёт миграция, а в БД хранятся значения ('on_hold'), а не имена (ON_HOLD)
list_status_type = Enum(ListStatus, name="list_status", values_callable=_values, create_type=False)
activity_type_type = Enum(ActivityType, name="activity_type", values_callable=_values, create_type=False)
