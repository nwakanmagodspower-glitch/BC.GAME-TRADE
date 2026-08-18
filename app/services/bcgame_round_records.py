from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import BCGameRound


class BCGameRoundRecordService:
    def __init__(self, db: Session):
        self.db = db

    def get_by_external_id(self, round_id: str) -> BCGameRound | None:
        return self.db.scalar(select(BCGameRound).where(BCGameRound.external_round_id == round_id))

    def record_result(
        self,
        *,
        round_id: str,
        start_rate: float,
        end_rate: float,
        start_rate_at: datetime | None = None,
        end_rate_at: datetime | None = None,
        source: str = 'BCGAME_ROUND_SYNC',
        raw_metadata: dict | None = None,
    ) -> BCGameRound:
        """Persist BC.GAME product truth, never an external-exchange substitute."""
        row = self.get_by_external_id(round_id)
        if row is None:
            raise ValueError('round must be observed before its result can be recorded')
        if start_rate <= 0 or end_rate <= 0:
            raise ValueError('BC.GAME Start Rate and End Rate must be positive')

        row.start_rate = float(start_rate)
        row.end_rate = float(end_rate)
        if start_rate_at is not None:
            row.start_rate_at = start_rate_at
        if end_rate_at is not None:
            row.end_rate_at = end_rate_at
        # Supplied How to Trade wording: UP only when End > Start; otherwise DOWN.
        row.actual_direction = 'UP' if end_rate > start_rate else 'DOWN'
        row.source = source
        row.raw_metadata = raw_metadata
        self.db.commit(); self.db.refresh(row)
        return row
