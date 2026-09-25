from datetime import datetime
from decimal import Decimal

from sqlalchemy import Integer, case, cast, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tag, TagHistory
from app.schemas.history import HistoryPoint, HistoryResponse, HistoryTag


async def query_history(
    session: AsyncSession,
    tag: Tag,
    start: datetime,
    end: datetime,
    limit: int,
    order: str,
    max_points: int | None,
) -> HistoryResponse:
    table = TagHistory
    filters = (table.tag_id == tag.id, table.recorded_at >= start, table.recorded_at < end)
    total = await session.scalar(select(func.count()).select_from(table).where(*filters))
    cap = min(limit, max_points) if max_points else limit
    downsampled = max_points is not None and total > cap
    points = []
    if not downsampled:
        ordering = (
            (table.recorded_at.asc(), table.id.asc())
            if order == "asc"
            else (table.recorded_at.desc(), table.id.desc())
        )
        rows = await session.scalars(select(table).where(*filters).order_by(*ordering).limit(cap))
        points = [
            HistoryPoint(
                recorded_at=row.recorded_at,
                source_timestamp=row.source_timestamp,
                value_numeric=row.value_numeric,
                value_boolean=row.value_boolean,
                value_text=row.value_text,
                quality=row.quality,
                source=row.source,
                first_timestamp=row.recorded_at,
                last_timestamp=row.recorded_at,
                has_invalid=row.quality != "GOOD",
            )
            for row in rows
        ]
    else:
        width = (end - start).total_seconds() / cap
        epoch = extract("epoch", table.recorded_at)
        if session.get_bind().dialect.name == "sqlite":
            epoch = (func.julianday(table.recorded_at) - 2440587.5) * 86400
        bucket = cast(func.floor((epoch - start.timestamp()) / width), Integer).label("bucket")
        statement = (
            select(
                bucket,
                func.min(table.recorded_at),
                func.max(table.recorded_at),
                func.count(),
                func.min(table.value_numeric),
                func.max(table.value_numeric),
                func.avg(table.value_numeric),
                func.sum(case((table.quality != "GOOD", 1), else_=0)),
                func.min(case((table.quality != "GOOD", table.quality), else_=None)),
                func.min(cast(table.value_boolean, Integer)),
                func.max(cast(table.value_boolean, Integer)),
                func.count(table.value_numeric),
                func.count(table.value_boolean),
                func.min(table.source),
                func.max(table.source),
                func.count(table.source),
            )
            .where(*filters)
            .group_by(bucket)
            .order_by(bucket.asc() if order == "asc" else bucket.desc())
        )
        for (
            _,
            first,
            last,
            count,
            low,
            high,
            avg,
            invalid,
            quality,
            bool_min,
            bool_max,
            numerics,
            booleans,
            first_source,
            last_source,
            sources,
        ) in (await session.execute(statement)).all():
            # A bucket containing any outage is a gap, never an averaged fake reading.
            # Mixed boolean buckets are also gaps: no fractional boolean values.
            numeric = (
                Decimal(str(avg)) if avg is not None and not invalid and numerics == count else None
            )
            boolean = (
                bool(bool_min)
                if not invalid and booleans == count and bool_min == bool_max
                else None
            )
            points.append(
                HistoryPoint(
                    recorded_at=first,
                    first_timestamp=first,
                    last_timestamp=last,
                    value_numeric=numeric,
                    value_boolean=boolean,
                    quality=quality or "GOOD",
                    source=first_source
                    if first_source == last_source and sources == count
                    else None,
                    minimum=low,
                    maximum=high,
                    average=Decimal(str(avg)) if avg is not None else None,
                    sample_count=count,
                    has_invalid=bool(invalid),
                )
            )
    return HistoryResponse(
        tag=HistoryTag.model_validate(tag),
        from_timestamp=start,
        to_timestamp=end,
        count=len(points),
        total_count=total,
        downsampled=downsampled,
        truncated=not downsampled and total > cap,
        points=points,
    )
