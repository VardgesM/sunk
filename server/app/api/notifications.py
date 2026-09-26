from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import NotificationDelivery, TelegramDestination
from app.schemas.alarms import DeliveryRead, DestinationInput

router = APIRouter(prefix="/api/notifications/telegram", tags=["notifications"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/destination")
async def destination(session: Session):
    row = await session.get(TelegramDestination, 1)
    return {"chat_id": row.chat_id if row else ""}


@router.patch("/destination", response_model=DestinationInput)
async def configure(payload: DestinationInput, session: Session):
    row = await session.get(TelegramDestination, 1)
    if row:
        row.chat_id = payload.chat_id
    else:
        session.add(TelegramDestination(id=1, chat_id=payload.chat_id))
    await session.commit()
    return payload


@router.post("/test", response_model=DeliveryRead, status_code=202)
async def test(session: Session):
    row = await session.get(TelegramDestination, 1)
    if not row:
        raise HTTPException(422, "Configure a Telegram destination first")
    delivery = NotificationDelivery(
        kind="TEST",
        chat_id=row.chat_id,
        message="Modbus Monitor: explicit Telegram test notification",
        status="PENDING",
        created_at=datetime.now(UTC),
    )
    session.add(delivery)
    await session.commit()
    return DeliveryRead.model_validate(delivery)


@router.get("/deliveries", response_model=list[DeliveryRead])
async def deliveries(
    session: Session, limit: int = Query(50, ge=1, le=200), event_id: int | None = Query(None, ge=1)
):
    query = select(NotificationDelivery)
    if event_id is not None:
        query = query.where(NotificationDelivery.event_id == event_id)
    return [
        DeliveryRead.model_validate(d)
        for d in await session.scalars(query.order_by(NotificationDelivery.id.desc()).limit(limit))
    ]
