"""
Push notification helper.

To actually send push notifications to the Flutter app you need a Firebase
project:

1. Create a project at https://console.firebase.google.com
2. Add your Flutter app (Android/iOS) to it and drop the generated
   google-services.json / GoogleService-Info.plist into the Flutter project
   (see frontend/README.md).
3. Project settings -> Service accounts -> Generate new private key.
   Save the downloaded JSON as backend/firebase_service_account.json
   (this file is gitignored - never commit it).
4. pip install firebase-admin
5. In the Flutter app, get the device's FCM token (see
   notification_service.dart) and POST it to /api/devices so the backend
   knows where to send alerts.

Until you do that setup, send_push_to_token() below just logs to the
console instead of failing, so the rest of the app works out of the box.
"""

import os
import logging

logger = logging.getLogger(__name__)

FIREBASE_CRED_PATH = os.path.join(os.path.dirname(__file__), "firebase_service_account.json")

_firebase_app = None
_firebase_available = False

if os.path.exists(FIREBASE_CRED_PATH):
    try:
        import firebase_admin
        from firebase_admin import credentials, messaging

        cred = credentials.Certificate(FIREBASE_CRED_PATH)
        _firebase_app = firebase_admin.initialize_app(cred)
        _firebase_available = True
    except Exception as e:  # pragma: no cover
        logger.warning("Firebase not initialized: %s", e)


def send_push_to_token(token: str, title: str, body: str, data: dict | None = None):
    """Send a single push notification. Falls back to logging if Firebase
    isn't configured yet, so local dev/testing never breaks."""
    if not _firebase_available:
        logger.info("[PUSH-STUB] to=%s title=%r body=%r data=%s", token, title, body, data)
        return {"stub": True, "sent": False}

    from firebase_admin import messaging

    message = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        data={k: str(v) for k, v in (data or {}).items()},
        token=token,
    )
    response = messaging.send(message)
    return {"stub": False, "sent": True, "message_id": response}


def send_push_to_many(tokens: list[str], title: str, body: str, data: dict | None = None):
    results = []
    for t in tokens:
        try:
            results.append(send_push_to_token(t, title, body, data))
        except Exception as e:
            logger.warning("Push failed for token %s: %s", t, e)
            results.append({"sent": False, "error": str(e)})
    return results
