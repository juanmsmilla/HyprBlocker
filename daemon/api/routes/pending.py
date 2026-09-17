"""Pending delayed-unblock API (prototype)."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from daemon import pending_unblock
from daemon.api.schemas import PendingUnblockResponse

router = APIRouter(prefix="/api", tags=["pending-unblock"])


def _remaining_seconds(effective_at: str) -> int:
    try:
        eff = datetime.fromisoformat(effective_at)
        if eff.tzinfo is None:
            eff = eff.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        return max(0, int((eff.astimezone(UTC) - now).total_seconds()))
    except ValueError:
        return 0


@router.get("/pending-unblocks", response_model=list[PendingUnblockResponse])
async def get_pending_unblocks():
    items = pending_unblock.list_pending()
    return [
        PendingUnblockResponse(
            id=p["id"],
            kind=p["kind"],
            block_id=p["block_id"],
            block_name=p["block_name"],
            created_at=p["created_at"],
            effective_at=p["effective_at"],
            remaining_seconds=_remaining_seconds(p["effective_at"]),
        )
        for p in items
    ]


@router.delete("/pending-unblocks/{pending_id}")
async def cancel_pending_unblock(pending_id: str):
    if not pending_unblock.cancel(pending_id):
        raise HTTPException(status_code=404, detail="Pending change not found")
    return {"status": "canceled", "id": pending_id}


@router.delete("/pending-unblocks")
async def cancel_all_pending_unblocks():
    n = pending_unblock.cancel_all()
    return {"status": "canceled", "count": n}
