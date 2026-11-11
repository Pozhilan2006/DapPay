from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Datetime values must be timezone-aware.")
        return value.astimezone(timezone.utc)

    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        del dialect
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=timezone.utc)
