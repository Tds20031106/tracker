from extensions import db
from datetime import datetime, timezone


def _utcnow():
    """Timezone-aware replacement for the deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Case(db.Model):
    __tablename__ = "cases"

    id = db.Column(db.Integer, primary_key=True)
    court_name = db.Column(db.String(255), nullable=False, default="")
    case_number = db.Column(db.String(255), nullable=False, default="")
    last_hearing_date = db.Column(db.Date, nullable=True)
    case_title = db.Column(db.String(500), nullable=False, default="")
    next_hearing_date = db.Column(db.Date, nullable=True)
    brief_history = db.Column(db.Text, nullable=True, default="")

    # Free-text status exactly as it might be phrased (kept for reference / detail view)
    affidavit_status_text = db.Column(db.Text, nullable=True, default="")

    # Normalized status used for CRUD + highlighting logic.
    # One of: "filed", "not_filed"
    affidavit_status = db.Column(db.String(20), nullable=False, default="not_filed")

    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "court_name": self.court_name,
            "case_number": self.case_number,
            "last_hearing_date": self.last_hearing_date.isoformat() if self.last_hearing_date else None,
            "case_title": self.case_title,
            "next_hearing_date": self.next_hearing_date.isoformat() if self.next_hearing_date else None,
            "brief_history": self.brief_history,
            "affidavit_status_text": self.affidavit_status_text,
            "affidavit_status": self.affidavit_status,
            "counter_affidavit_filed": self.affidavit_status == "filed",
        }


class Device(db.Model):
    """Stores FCM device tokens so the backend knows where to push alerts."""
    __tablename__ = "devices"

    id = db.Column(db.Integer, primary_key=True)
    fcm_token = db.Column(db.String(500), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)


class NotificationLog(db.Model):
    """Prevents sending the same 10-day-reminder more than once per case."""
    __tablename__ = "notification_log"

    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=False)
    next_hearing_date = db.Column(db.Date, nullable=False)
    sent_at = db.Column(db.DateTime, default=_utcnow)
