from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    OnboardingStep,
    User,
    UserRole,
    UserStatus,
    VerificationRequest,
    VerificationStatus,
)


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
            .where(VerificationRequest.status.in_([VerificationStatus.COLLECTING, VerificationStatus.RESUBMIT]))
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
        if file_id not in proofs:
            proofs.append(file_id)
        request.deposit_proof_file_ids = proofs
        self.db.commit()
        return request

    def submit(self, user: User) -> VerificationRequest:
        request = self.current_request(user)
        if not request.bcgame_user_id or not request.profile_proof_file_id or not request.deposit_proof_file_ids:
            raise ValueError('Verification packet is incomplete')
        request.status = VerificationStatus.SUBMITTED
        request.submitted_at = utcnow()
        user.onboarding_step = OnboardingStep.REVIEW
        self.db.commit()
        self.db.refresh(request)
        return request

    def review(self, request_id: int, admin_id: int, action: str) -> tuple[VerificationRequest, User]:
        request = self.db.get(VerificationRequest, request_id)
        if request is None:
            raise ValueError('Verification request not found')
        user = self.db.get(User, request.user_id)
        if user is None:
            raise ValueError('User not found')

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
            request.bcgame_user_id = None
            request.profile_proof_file_id = None
            request.deposit_proof_file_ids = []
        else:
            raise ValueError('Unknown review action')

        self.db.commit()
        return request, user
