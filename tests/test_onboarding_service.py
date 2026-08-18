from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.entities import OnboardingStep, UserStatus, VerificationStatus
from app.services.onboarding import OnboardingService


def make_service():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    return session, OnboardingService(session)


def test_verification_flow_requires_complete_packet_and_remembers_approval():
    db, service = make_service()
    try:
        telegram_user = SimpleNamespace(id=12345, username='tester', first_name='Test')
        user = service.get_or_create_user(telegram_user)
        assert user.status == UserStatus.PENDING
        assert user.onboarding_step == OnboardingStep.START

        service.set_step(user, OnboardingStep.BC_ID)
        request = service.set_bcgame_user_id(user, 'BC123')
        assert request.bcgame_user_id == 'BC123'
        assert user.onboarding_step == OnboardingStep.PROFILE_PROOF

        service.set_profile_proof(user, 'profile-file')
        service.add_deposit_proof(user, 'deposit-file-1')
        submitted = service.submit(user)
        assert submitted.status == VerificationStatus.SUBMITTED
        assert user.onboarding_step == OnboardingStep.REVIEW

        _, approved_user = service.review(submitted.id, admin_id=999, action='approve')
        assert approved_user.status == UserStatus.APPROVED
        assert approved_user.onboarding_step == OnboardingStep.APPROVED
        assert approved_user.approved_by == 999
    finally:
        db.close()
