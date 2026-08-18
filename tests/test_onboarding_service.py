from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.entities import OnboardingStep, UserStatus, VerificationRequest, VerificationStatus
from app.services.onboarding import OnboardingService


def make_service():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    return session, OnboardingService(session)


def build_submitted_request(service):
    telegram_user = SimpleNamespace(id=12345, username='tester', first_name='Test')
    user = service.get_or_create_user(telegram_user)
    service.set_step(user, OnboardingStep.BC_ID)
    service.set_bcgame_user_id(user, 'BC123')
    service.set_profile_proof(user, 'profile-file')
    service.add_deposit_proof(user, 'deposit-file-1')
    return user, service.submit(user)


def test_verification_flow_requires_complete_packet_and_remembers_approval():
    db, service = make_service()
    try:
        user, submitted = build_submitted_request(service)
        assert submitted.status == VerificationStatus.SUBMITTED
        assert user.onboarding_step == OnboardingStep.REVIEW
        _, approved_user, changed = service.review(submitted.id, admin_id=999, action='approve')
        assert changed is True
        assert approved_user.status == UserStatus.APPROVED
        assert approved_user.onboarding_step == OnboardingStep.APPROVED
        assert approved_user.approved_by == 999
        _, same_user, changed_again = service.review(submitted.id, admin_id=999, action='approve')
        assert changed_again is False
        assert same_user.status == UserStatus.APPROVED
        with pytest.raises(ValueError): service.review(submitted.id, admin_id=999, action='reject')
    finally:
        db.close()


def test_resubmit_preserves_old_packet_and_creates_new_packet():
    db, service = make_service()
    try:
        user, submitted = build_submitted_request(service)
        old_id = submitted.id
        request, user, changed = service.review(old_id, admin_id=999, action='resubmit')
        assert changed is True
        assert request.status == VerificationStatus.RESUBMIT
        assert user.status == UserStatus.PENDING
        assert user.onboarding_step == OnboardingStep.BC_ID
        assert request.bcgame_user_id == 'BC123'
        assert request.profile_proof_file_id == 'profile-file'
        assert request.deposit_proof_file_ids == ['deposit-file-1']

        new_request = service.set_bcgame_user_id(user, 'BC456')
        assert new_request.id != old_id
        assert new_request.status == VerificationStatus.COLLECTING
        assert new_request.bcgame_user_id == 'BC456'
        history = db.scalars(select(VerificationRequest).where(VerificationRequest.user_id == user.id).order_by(VerificationRequest.id)).all()
        assert len(history) == 2
        assert history[0].status == VerificationStatus.RESUBMIT
        assert history[1].status == VerificationStatus.COLLECTING
    finally:
        db.close()
