# Legal Case Tracker

Flutter frontend + Flask backend to track legal cases, highlight cases
where the counter affidavit hasn't been filed, and alert you 10 days
before the next hearing date (in-app + push).

## Folder structure

```
backend/    Flask API + SQLite database
frontend/   Flutter app (Android/iOS/web)
```

## 1. Backend setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Import your Excel sheet into the database (run this once, or again with
# --wipe whenever you get an updated master sheet):
python import_excel.py /path/to/Cases_List_PDUNIPPD.xlsx --wipe

# Start the server
python app.py
```

The API will be live at `http://localhost:5000/api`. Key endpoints:

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/cases` | List cases. Filters: `?affidavit_status=not_filed`, `?search=`, `?upcoming=10` |
| GET | `/api/cases/<id>` | Get one case |
| POST | `/api/cases` | Create a case |
| PUT/PATCH | `/api/cases/<id>` | Update a case |
| DELETE | `/api/cases/<id>` | Delete a case |
| GET | `/api/cases/summary` | Dashboard counts |
| GET | `/api/alerts/upcoming` | Cases with hearing within 10 days (in-app banner uses this) |
| POST | `/api/alerts/run-now` | Manually trigger the push-notification check |
| POST | `/api/devices` | Register a device's FCM token for push |

A background job (APScheduler) checks every 24 hours for hearings within
10 days and sends a push notification once per case per hearing date
(tracked in the `notification_log` table so you're not spammed).

### Re-importing an updated Excel sheet later
Just re-run `python import_excel.py your_file.xlsx --wipe`. Note this
replaces all cases — if you've since edited cases from the app, those
edits will be lost. For ongoing use, treat the database (not the Excel
file) as the source of truth after the first import, and just use the
app's Add/Edit/Delete instead of re-importing.

## 1b. Deploying the backend to Render

Minimal changes for Render are already made (`Procfile`, `gunicorn` in
requirements.txt, and `app.py` reads the `PORT` env var). Steps:

1. Push the `backend/` folder to a GitHub repo (include `cases.db` — it's
   already populated with your imported cases, so you don't need to
   re-run the importer on Render).
2. On https://dashboard.render.com → New → Web Service → connect your repo.
3. Set **Root Directory** to `backend`.
4. Build Command: `pip install -r requirements.txt`
5. Start Command: leave blank (Render reads the `Procfile` automatically),
   or explicitly set `gunicorn app:app --bind 0.0.0.0:$PORT`.
6. Deploy. Render gives you a URL like `https://your-app-name.onrender.com`.
7. Test it: visit `https://your-app-name.onrender.com/api/cases/summary`
   in a browser — you should see the JSON counts.

**Important caveat about SQLite on Render's free tier:** the filesystem
is not guaranteed to persist across deploys (it does persist across
restarts/sleep, but a new deploy can reset it back to whatever's in your
repo). For a personal tracker this is usually fine since you're not
redeploying often, but if you want guaranteed persistence:
- Add a Render **Persistent Disk** (small paid add-on) mounted at
  `/opt/render/project/src/backend`, or
- Add Render's managed **PostgreSQL** and change
  `SQLALCHEMY_DATABASE_URI` in `app.py` to the Postgres connection
  string Render gives you (would also need `psycopg2-binary` added to
  requirements.txt). Ask if you want this wired up.

## 2. Frontend setup

```bash
cd frontend
flutter pub get
```

Open `lib/services/api_service.dart` and change the one `baseUrl` line to
your Render URL:
```dart
static const String baseUrl = 'https://your-app-name.onrender.com/api';
```
(Local-only testing instead: `http://localhost:5000/api` for web/desktop,
`http://10.0.2.2:5000/api` for Android emulator.)

Run it — pick whichever target you have set up:
```bash
flutter run -d chrome     # web (matches what you were just testing)
flutter run                # connected Android/iOS device or emulator
```

If you don't have Flutter installed yet:
1. Install the SDK: https://docs.flutter.dev/get-started/install
2. Run `flutter doctor` and fix anything it flags (Chrome for web is
   usually already fine; Android Studio needed for Android).
3. `cd frontend && flutter pub get && flutter run -d chrome`

### What it does
- Lists all cases; any case where the counter affidavit is **not filed**
  is highlighted with a red border/background and a "CA NOT FILED" tag.
- Orange banner at the top shows cases with a hearing in the next 10 days.
- Search bar + filter chips (All / CA Not Filed / CA Filed).
- Tap a case for full details; edit or delete from there.
- "+" button to add a new case.

## 3. Push notifications (optional but requested)

Push notifications need a Firebase project — there's no way around this
for Flutter push, and it can't be fully pre-configured for you since it
requires your own Google account/project. Steps:

1. Go to https://console.firebase.google.com and create a project.
2. Add your Android app (and/or iOS app) — use the same package name
   as in `frontend/android/app/build.gradle` (`applicationId`).
3. Download `google-services.json` and place it in
   `frontend/android/app/google-services.json`.
   (For iOS: download `GoogleService-Info.plist` into `frontend/ios/Runner/`.)
4. Follow the FlutterFire docs to add the Gradle plugin:
   https://firebase.flutter.dev/docs/overview/ — or just run
   `flutterfire configure` from the `frontend/` folder if you have the
   FlutterFire CLI installed.
5. In `frontend/lib/main.dart`, uncomment the two Firebase lines:
   ```dart
   await Firebase.initializeApp();
   await NotificationService.init();
   ```
6. In the Firebase console: Project settings → Service accounts →
   Generate new private key. Save the JSON as
   `backend/firebase_service_account.json` (already gitignored).
7. `pip install firebase-admin` (already in requirements.txt).

Once that's done, the app will register its device token with the
backend automatically on launch, and the daily scheduler will push a
real notification 10 days before each hearing.

**Until you do this setup, everything else still works** — the backend
just logs "[PUSH-STUB]" instead of sending, and the in-app orange banner
still shows upcoming hearings regardless.

## Notes on the imported data

The Excel sheet's "Status of Reply/Counter affidavit" column is free
text (e.g. "counter affidavit filed", "counter affidavit to be filed...",
"sent for approval..."). The importer makes a best-effort guess at
Filed / Not Filed from keywords, but you should review the initial
import and correct any misclassified cases from the app (each case's
edit screen has a Filed / Not Filed toggle) since this drives the red
highlighting.
