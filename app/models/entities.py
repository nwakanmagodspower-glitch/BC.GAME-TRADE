import enum
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserStatus(str, enum.Enum):
    PENDING = 'PENDING'
    APPROVED = 'APPROVED'
    REJECTED = 'REJECTED'
    SUSPENDED = 'SUSPENDED'


class UserRole(str, enum.Enum):
    USER = 'USER'
    ADMIN = 'ADMIN'
    OWNER = 'OWNER'


class OnboardingStep(str, enum.Enum):
    START = 'START'
    REGISTRATION = 'REGISTRATION'
    DEPOSIT = 'DEPOSIT'
    BC_ID = 'BC_ID'
    PROFILE_PROOF = 'PROFILE_PROOF'
    DEPOSIT_PROOF = 'DEPOSIT_PROOF'
    REVIEW = 'REVIEW'
    APPROVED = 'APPROVED'
    RESUBMIT = 'RESUBMIT'


class VerificationStatus(str, enum.Enum):
    COLLECTING = 'COLLECTING'
    SUBMITTED = 'SUBMITTED'
    APPROVED = 'APPROVED'
    REJECTED = 'REJECTED'
    RESUBMIT = 'RESUBMIT'


class SignalDirection(str, enum.Enum):
    UP = 'UP'
    DOWN = 'DOWN'
    NO_TRADE = 'NO_TRADE'


class SignalStatus(str, enum.Enum):
    CANDIDATE = 'CANDIDATE'
    WAITING_ENTRY = 'WAITING_ENTRY'
    ACTIVE = 'ACTIVE'
    CANCELLED = 'CANCELLED'
    EXPIRED = 'EXPIRED'
    WIN = 'WIN'
    LOSS = 'LOSS'
    TIE = 'TIE'
    NO_TRADE = 'NO_TRADE'


class BroadcastStatus(str, enum.Enum):
    DRAFT = 'DRAFT'
    QUEUED = 'QUEUED'
    SENDING = 'SENDING'
    COMPLETE = 'COMPLETE'
    FAILED = 'FAILED'


class DeliveryStatus(str, enum.Enum):
    PENDING = 'PENDING'
    SENT = 'SENT'
    FAILED = 'FAILED'


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[UserStatus] = mapped_column(Enum(UserStatus), default=UserStatus.PENDING, index=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.USER)
    onboarding_step: Mapped[OnboardingStep] = mapped_column(Enum(OnboardingStep), default=OnboardingStep.START, index=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VerificationRequest(Base):
    __tablename__ = 'verification_requests'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    bcgame_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    profile_proof_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    deposit_proof_file_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[VerificationStatus] = mapped_column(Enum(VerificationStatus), default=VerificationStatus.COLLECTING, index=True)
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BCGameRound(Base):
    """Compact product-truth record for one observed BC.GAME Up/Down round."""
    __tablename__ = 'bcgame_rounds'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_round_id: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True, index=True)
    game_market: Mapped[str] = mapped_column(String(40), default='BTC/USD', index=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=5)
    stake_band: Mapped[str] = mapped_column(String(40), default='1-50', index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    order_closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    start_rate_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_rate_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    start_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_direction: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    up_payout_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    down_payout_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    up_pool_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    down_pool_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    up_players: Mapped[int | None] = mapped_column(Integer, nullable=True)
    down_players: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    raw_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Signal(Base):
    __tablename__ = 'signals'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requested_by_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True, index=True)
    bcgame_round_id: Mapped[int | None] = mapped_column(ForeignKey('bcgame_rounds.id'), nullable=True, index=True)
    market: Mapped[str] = mapped_column(String(40), default='BTC/USD', index=True)
    product: Mapped[str] = mapped_column(String(60), default='BC_UPDOWN_5S')
    direction: Mapped[SignalDirection] = mapped_column(Enum(SignalDirection), index=True)
    status: Mapped[SignalStatus] = mapped_column(Enum(SignalStatus), index=True)
    strategy_version: Mapped[str] = mapped_column(String(80), index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    entry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expiry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reference_entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference_expiry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    features_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class SignalNotification(Base):
    __tablename__ = 'signal_notifications'
    __table_args__ = (UniqueConstraint('signal_id', 'event', name='uq_signal_notification_event'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey('signals.id'), index=True)
    event: Mapped[str] = mapped_column(String(40), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Broadcast(Base):
    __tablename__ = 'broadcasts'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[BroadcastStatus] = mapped_column(Enum(BroadcastStatus), default=BroadcastStatus.DRAFT, index=True)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BroadcastDelivery(Base):
    __tablename__ = 'broadcast_deliveries'
    __table_args__ = (UniqueConstraint('broadcast_id', 'user_id', name='uq_broadcast_delivery_user'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    broadcast_id: Mapped[int] = mapped_column(ForeignKey('broadcasts.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    status: Mapped[DeliveryStatus] = mapped_column(Enum(DeliveryStatus), default=DeliveryStatus.PENDING, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RuntimeSetting(Base):
    __tablename__ = 'runtime_settings'
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
