from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.entities import (
    OnboardingStep,
    User,
    UserRole,
    UserStatus,
    VerificationRequest,
    VerificationDelivery,
    VerificationDeliveryStatus,
    VerificationStatus,
)
from app.core.config import get_settings

settings = get_settings()


def utcnow():
    return datetime.now(timezone.utc)


class OnboardingService:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create_user(self, telegram_user) -> User:
        user = self.db.scalar(select(User).where(User.telegram_user_id == telegram_user.id))
        if user is None:
            user = User(
                telegram_user_id=telegram_user.id,
                telegram_username=telegram_user.username,
                first_name=telegram_user.first_name,
                status=UserStatus.PENDING,
                role=UserRole.USER,
                onboarding_step=OnboardingStep.START,
            )
            self.db.add(user)
        else:
            user.telegram_username = telegram_user.username
            user.first_name = telegram_user.first_name
            user.last_seen_at = utcnow()
        self.db.commit()
        self.db.refresh(user)
        return user

    def current_request(self, user: User) -> VerificationRequest:
        request = self.db.scalar(
            select(VerificationRequest)
            .where(VerificationRequest.user_id == user.id)
            .where(VerificationRequest.status == VerificationStatus.COLLECTING)
            .order_by(VerificationRequest.id.desc())
        )
        if request is None:
            request = VerificationRequest(user_id=user.id, status=VerificationStatus.COLLECTING)
            self.db.add(request)
            self.db.commit()
            self.db.refresh(request)
        return request

    def set_step(self, user: User, step: OnboardingStep) -> None:
        user.onboarding_step = step
        self.db.commit()

    def set_bcgame_user_id(self, user: User, value: str) -> VerificationRequest:
        request = self.current_request(user)
        request.bcgame_user_id = value.strip()
        user.onboarding_step = OnboardingStep.PROFILE_PROOF
        self.db.commit()
        return request

    def set_profile_proof(self, user: User, file_id: str) -> VerificationRequest:
        request = self.current_request(user)
        request.profile_proof_file_id = file_id
        user.onboarding_step = OnboardingStep.DEPOSIT_PROOF
        self.db.commit()
        return request

    def add_deposit_proof(self, user: User, file_id: str) -> VerificationRequest:
        request = self.current_request(user)
        proofs = list(request.deposit_proof_file_ids or [])
        now = utcnow()
        if request.last_evidence_at is not None:
            previous = request.last_evidence_at
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=timezone.utc)
            if (now - previous).total_seconds() < settings.verification_min_evidence_interval_seconds:
                raise ValueError('Please wait briefly before sending another screenshot.')
        if file_id not in proofs and len(proofs) >= settings.verification_max_deposit_proofs:
            raise ValueError(f'You can submit at most {settings.verification_max_deposit_proofs} deposit screenshots.')
        if file_id not in proofs:
            proofs.append(file_id)
        request.deposit_proof_file_ids = proofs
        request.last_evidence_at = now
        self.db.commit()
        return request

    def submit(self, user: User) -> VerificationRequest:
        if user.status in (UserStatus.APPROVED, UserStatus.SUSPENDED):
            raise ValueError('Verification is not available for this account state')

        existing = self.db.scalar(
            select(VerificationRequest)
            .where(VerificationRequest.user_id == user.id)
            .where(VerificationRequest.status == VerificationStatus.SUBMITTED)
            .order_by(VerificationRequest.id.desc())
        )
        if existing is not None:
            user.onboarding_step = OnboardingStep.REVIEW
            self._ensure_delivery(existing)
            self.db.commit()
            return existing

        request = self.current_request(user)
        if not request.bcgame_user_id or not request.profile_proof_file_id or not request.deposit_proof_file_ids:
            raise ValueError('Verification packet is incomplete')
        request.status = VerificationStatus.SUBMITTED
        request.submitted_at = utcnow()
        user.onboarding_step = OnboardingStep.REVIEW
        self._ensure_delivery(request)
        self.db.commit()
        self.db.refresh(request)
        return request

    def _ensure_delivery(self, request: VerificationRequest) -> VerificationDelivery:
        delivery = self.db.scalar(
            select(VerificationDelivery).where(
                VerificationDelivery.verification_request_id == request.id
            )
        )
        if delivery is None:
            delivery = VerificationDelivery(
                verification_request_id=request.id,
                status=VerificationDeliveryStatus.PENDING,
            )
            self.db.add(delivery)
        return delivery

    def _purge_evidence(self, request: VerificationRequest) -> None:
        """Remove temporary verification evidence after an owner decision.

        BC.GAME account IDs and Telegram file IDs exist only long enough to
        complete owner review. They are not retained as user profile/history.
        """
        request.bcgame_user_id = None
        request.profile_proof_file_id = None
        request.deposit_proof_file_ids = None
        request.last_evidence_at = None
        self.db.execute(
            delete(VerificationDelivery).where(
                VerificationDelivery.verification_request_id == request.id
            )
        )

    def review(self, request_id: int, admin_id: int, action: str) -> tuple[VerificationRequest, User, bool]:
        request = self.db.get(VerificationRequest, request_id)
        if request is None:
            raise ValueError('Verification request not found')
        user = self.db.get(User, request.user_id)
        if user is None:
            raise ValueError('User not found')

        terminal = {
            VerificationStatus.APPROVED: 'approve',
            VerificationStatus.REJECTED: 'reject',
            VerificationStatus.RESUBMIT: 'resubmit',
        }
        previous_action = terminal.get(request.status)
        if previous_action:
            if previous_action == action:
                return request, user, False
            raise ValueError(f'Request already reviewed as {previous_action}')

        if request.status != VerificationStatus.SUBMITTED:
            raise ValueError('Request is not waiting for review')
        delivery = self.db.scalar(
            select(VerificationDelivery).where(
                VerificationDelivery.verification_request_id == request.id
            )
        )
        if delivery is None or delivery.status != VerificationDeliveryStatus.SENT:
            raise ValueError('Verification evidence has not finished delivery to the owner')

        request.reviewed_by = admin_id
        request.reviewed_at = utcnow()

        if action == 'approve':
            request.status = VerificationStatus.APPROVED
            user.status = UserStatus.APPROVED
            user.onboarding_step = OnboardingStep.APPROVED
            user.approved_at = utcnow()
            user.approved_by = admin_id
        elif action == 'reject':
            request.status = VerificationStatus.REJECTED
            user.status = UserStatus.REJECTED
        elif action == 'resubmit':
            request.status = VerificationStatus.RESUBMIT
            user.status = UserStatus.PENDING
            user.onboarding_step = OnboardingStep.BC_ID
        else:
            raise ValueError('Unknown review action')

        # Evidence is temporary. Once the owner has made a decision, retain
        # only the review/access state and purge BC.GAME ID + Telegram file IDs.
        self._purge_evidence(request)

        self.db.commit()
        self.db.refresh(request)
        self.db.refresh(user)
        return request, user, True
