from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings

settings = get_settings()


@dataclass(frozen=True)
class BCGameAdapter:
    """Configuration boundary for BC.GAME-specific product routes.

    V1 does not automate trade placement. This adapter keeps BC.GAME product
    identity and destination URLs out of Telegram handlers and strategy logic so
    route/API changes can be repaired in one integration layer.
    """

    product: str
    registration_url: str | None
    deposit_url: str | None
    updown_url: str | None

    @classmethod
    def from_settings(cls) -> 'BCGameAdapter':
        return cls(
            product=settings.default_product,
            registration_url=settings.bcgame_registration_url,
            deposit_url=settings.bcgame_deposit_url,
            updown_url=settings.bcgame_updown_url,
        )


bcgame_adapter = BCGameAdapter.from_settings()
