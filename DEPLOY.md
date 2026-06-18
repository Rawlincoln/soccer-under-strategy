# Deploy Under Goals Live Online

## Option 1 — Quick share (free, temporary URL)

Double-click **`start-online.bat`**

- Starts the app on port 5050
- Opens a **trycloudflare.com** public link
- **Keep the window open** while sharing — URL changes each restart

## Option 2 — Permanent hosting on Render (free)

1. Push this folder to GitHub (or use Render's direct deploy)
2. Go to [render.com](https://render.com) → **New Web Service**
3. Connect the repo
4. Render auto-detects `render.yaml` or use:
   - **Build:** `pip install -r requirements.txt`
   - **Start:** `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120`
5. Deploy — you get a permanent `*.onrender.com` URL

Free tier sleeps after 15 min idle; first load may take ~30s.

## Option 3 — LAN access (same Wi‑Fi)

While the app runs, others on your network can use:

`http://192.168.0.15:5050`

(Your IP may differ — check the terminal when starting `app.py`.)