from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.webhook import TelegramUpdateReceipt


class WebhookReceiptService:
    def __init__(self, db: Session):
        self.db = db

    def claim(self, update_id: int) -> bool:
        self.db.add(TelegramUpdateReceipt(update_id=update_id))
        try:
            self.db.commit()
            return True
        except IntegrityError:
            self.db.rollback()
            return False
