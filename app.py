import os
import logging
from datetime import datetime, date, timedelta

from flask import Flask, request, jsonify
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler

from extensions import db
from models import Case, Device, NotificationLog
from notifications import send_push_to_many

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
CORS(app)  # allow the Flutter app (any origin) to call this API

database_url = os.environ.get("postgresql://tracker_t0to_user:n5O9uJx5yUqpUeTqMzSKPJWPfe1WxQIl@dpg-d97dggvavr4c738ae31g-a/tracker_t0to")
if database_url:
    # Render (and some other hosts) hand out "postgres://" URLs, but
    # SQLAlchemy 2.x / psycopg2 require the "postgresql://" scheme.
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(BASE_DIR, 'cases.db')}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

ALERT_WINDOW_DAYS = 10  # how many days before next hearing to start alerting


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def parse_date(value):
    """Accepts 'YYYY-MM-DD' or None. Returns a date object or None."""
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def case_from_json(payload, case=None):
    case = case or Case()
    case.court_name = payload.get("court_name", case.court_name or "")
    case.case_number = payload.get("case_number", case.case_number or "")
    case.case_title = payload.get("case_title", case.case_title or "")
    case.brief_history = payload.get("brief_history", case.brief_history or "")
    case.affidavit_status_text = payload.get("affidavit_status_text", case.affidavit_status_text or "")

    status = payload.get("affidavit_status", case.affidavit_status or "not_filed")
    if status not in ("filed", "not_filed"):
        status = "not_filed"
    case.affidavit_status = status

    if "last_hearing_date" in payload:
        case.last_hearing_date = parse_date(payload.get("last_hearing_date"))
    if "next_hearing_date" in payload:
        case.next_hearing_date = parse_date(payload.get("next_hearing_date"))

    return case


# --------------------------------------------------------------------------
# CRUD routes
# --------------------------------------------------------------------------

@app.route("/api/cases", methods=["GET"])
def list_cases():
    """
    Optional query params:
      ?affidavit_status=not_filed   filter by status
      ?upcoming=10                  only cases whose next hearing is within N days
      ?search=text                  matches case_number / case_title / court_name
    """
    query = Case.query

    status = request.args.get("affidavit_status")
    if status in ("filed", "not_filed"):
        query = query.filter(Case.affidavit_status == status)

    search = request.args.get("search")
    if search:
        like = f"%{search}%"
        query = query.filter(
            (Case.case_number.ilike(like))
            | (Case.case_title.ilike(like))
            | (Case.court_name.ilike(like))
        )

    upcoming = request.args.get("upcoming")
    if upcoming:
        try:
            days = int(upcoming)
            today = date.today()
            cutoff = today + timedelta(days=days)
            query = query.filter(
                Case.next_hearing_date.isnot(None),
                Case.next_hearing_date >= today,
                Case.next_hearing_date <= cutoff,
            )
        except ValueError:
            pass

    query = query.order_by(Case.next_hearing_date.asc().nullslast())
    cases = query.all()
    return jsonify([c.to_dict() for c in cases])


@app.route("/api/cases/<int:case_id>", methods=["GET"])
def get_case(case_id):
    case = Case.query.get_or_404(case_id)
    return jsonify(case.to_dict())


@app.route("/api/cases", methods=["POST"])
def create_case():
    payload = request.get_json(force=True) or {}
    case = case_from_json(payload)
    db.session.add(case)
    db.session.commit()
    return jsonify(case.to_dict()), 201


@app.route("/api/cases/<int:case_id>", methods=["PUT", "PATCH"])
def update_case(case_id):
    case = Case.query.get_or_404(case_id)
    payload = request.get_json(force=True) or {}
    case_from_json(payload, case=case)
    db.session.commit()
    return jsonify(case.to_dict())


@app.route("/api/cases/<int:case_id>", methods=["DELETE"])
def delete_case(case_id):
    case = Case.query.get_or_404(case_id)
    db.session.delete(case)
    db.session.commit()
    return jsonify({"deleted": True, "id": case_id})


@app.route("/api/cases/summary", methods=["GET"])
def summary():
    """Quick counts for a dashboard header."""
    total = Case.query.count()
    not_filed = Case.query.filter(Case.affidavit_status == "not_filed").count()
    today = date.today()
    cutoff = today + timedelta(days=ALERT_WINDOW_DAYS)
    upcoming = Case.query.filter(
        Case.next_hearing_date.isnot(None),
        Case.next_hearing_date >= today,
        Case.next_hearing_date <= cutoff,
    ).count()
    return jsonify({
        "total_cases": total,
        "counter_affidavit_not_filed": not_filed,
        "hearings_within_10_days": upcoming,
    })


# --------------------------------------------------------------------------
# Device registration for push notifications
# --------------------------------------------------------------------------

@app.route("/api/devices", methods=["POST"])
def register_device():
    payload = request.get_json(force=True) or {}
    token = payload.get("fcm_token")
    if not token:
        return jsonify({"error": "fcm_token is required"}), 400

    existing = Device.query.filter_by(fcm_token=token).first()
    if not existing:
        db.session.add(Device(fcm_token=token))
        db.session.commit()
    return jsonify({"registered": True})


# --------------------------------------------------------------------------
# 10-day-before-hearing alert logic (in-app + push)
# --------------------------------------------------------------------------

@app.route("/api/alerts/upcoming", methods=["GET"])
def upcoming_alerts():
    """Used by the Flutter app to show an in-app banner/list on launch."""
    today = date.today()
    cutoff = today + timedelta(days=ALERT_WINDOW_DAYS)
    cases = Case.query.filter(
        Case.next_hearing_date.isnot(None),
        Case.next_hearing_date >= today,
        Case.next_hearing_date <= cutoff,
    ).order_by(Case.next_hearing_date.asc()).all()

    results = []
    for c in cases:
        days_left = (c.next_hearing_date - today).days
        d = c.to_dict()
        d["days_until_hearing"] = days_left
        results.append(d)
    return jsonify(results)


def check_and_send_push_alerts():
    """Runs daily. Sends a push notification for every case whose next
    hearing is within ALERT_WINDOW_DAYS, once per case per hearing date."""
    with app.app_context():
        today = date.today()
        cutoff = today + timedelta(days=ALERT_WINDOW_DAYS)
        cases = Case.query.filter(
            Case.next_hearing_date.isnot(None),
            Case.next_hearing_date >= today,
            Case.next_hearing_date <= cutoff,
        ).all()

        if not cases:
            return

        tokens = [d.fcm_token for d in Device.query.all()]
        if not tokens:
            logger.info("No registered devices; skipping push, %d case(s) due.", len(cases))

        for c in cases:
            already_sent = NotificationLog.query.filter_by(
                case_id=c.id, next_hearing_date=c.next_hearing_date
            ).first()
            if already_sent:
                continue

            days_left = (c.next_hearing_date - today).days
            title = "Upcoming Hearing Reminder"
            body = f"{c.case_number} - {c.case_title[:60]} - hearing in {days_left} day(s) on {c.next_hearing_date.isoformat()}"

            if tokens:
                send_push_to_many(tokens, title, body, data={"case_id": c.id})

            db.session.add(NotificationLog(case_id=c.id, next_hearing_date=c.next_hearing_date))
            db.session.commit()
            logger.info("Alert processed for case %s (%d days left)", c.case_number, days_left)


scheduler = BackgroundScheduler()
scheduler.add_job(check_and_send_push_alerts, "interval", hours=24, id="daily_hearing_check")


@app.route("/api/alerts/run-now", methods=["POST"])
def run_alerts_now():
    """Manual trigger, handy for testing without waiting for the daily job."""
    check_and_send_push_alerts()
    return jsonify({"ran": True})


with app.app_context():
    db.create_all()

# Start the scheduler as soon as the module loads - this runs whether the
# app is launched via `python app.py` (local dev) or via gunicorn on Render.
if not scheduler.running:
    scheduler.start()
    check_and_send_push_alerts()  # run once immediately at startup too

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
