"""
Secure web dashboard for the AskUs Telegram Bot.
Shows groups, participants, questions, and usage stats.

Run: python dashboard.py
Requires: DASHBOARD_PASSWORD env var (or defaults to a random one printed at startup)
"""

import os
import secrets
import functools
import logging
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from pathlib import Path

# Load .env file if present (no extra dependency needed)
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))

from flask import (
    Flask,
    render_template_string,
    request,
    redirect,
    url_for,
    session,
    flash,
)
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Configuration ---
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
DATABASE_NAME = os.getenv("DATABASE_NAME", "telegram_bot")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8050"))
SECRET_KEY = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not DASHBOARD_PASSWORD:
    DASHBOARD_PASSWORD = secrets.token_urlsafe(16)
    logger.warning(
        "No DASHBOARD_PASSWORD set. Generated temporary password: %s",
        DASHBOARD_PASSWORD,
    )

# --- MongoDB ---
mongo_client = None
db = None


def connect_to_mongodb():
    global mongo_client, db
    try:
        mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        mongo_client.admin.command("ping")
        db = mongo_client[DATABASE_NAME]
        logger.info("Dashboard connected to MongoDB")
        return True
    except ConnectionFailure as e:
        logger.error("Failed to connect to MongoDB: %s", e)
        return False


# --- Telegram API ---
def telegram_send_message(chat_id, text, topic_id=None):
    """Send a message via the Telegram Bot API. Returns (ok, description)."""
    if not BOT_TOKEN:
        return False, "BOT_TOKEN not configured"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if topic_id:
        payload["message_thread_id"] = int(topic_id)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            return body.get("ok", False), "Message sent"
    except urllib.error.HTTPError as e:
        body = json.loads(e.read())
        return False, body.get("description", str(e))
    except Exception as e:
        return False, str(e)


# --- Flask app ---
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return wrapper


# --- HTML Template ---
TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AskUs Bot Dashboard</title>
<style>
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #242736;
    --border: #2e3142;
    --text: #e4e6f0;
    --text-muted: #8b8fa3;
    --accent: #6c8cff;
    --accent-hover: #8aa4ff;
    --green: #4ade80;
    --orange: #fb923c;
    --red: #f87171;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    min-height: 100vh;
  }
  a { color: var(--accent); text-decoration: none; }
  a:hover { color: var(--accent-hover); text-decoration: underline; }

  /* Login page */
  .login-container {
    display: flex; align-items: center; justify-content: center;
    min-height: 100vh; padding: 1rem;
  }
  .login-box {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 2.5rem; width: 100%; max-width: 380px;
  }
  .login-box h1 { font-size: 1.4rem; margin-bottom: 0.5rem; }
  .login-box p { color: var(--text-muted); margin-bottom: 1.5rem; font-size: 0.9rem; }
  .login-box input[type="password"] {
    width: 100%; padding: 0.7rem 1rem; border-radius: 8px;
    border: 1px solid var(--border); background: var(--bg);
    color: var(--text); font-size: 1rem; margin-bottom: 1rem;
  }
  .login-box input:focus { outline: none; border-color: var(--accent); }
  .btn {
    display: inline-block; padding: 0.7rem 1.5rem; border-radius: 8px;
    background: var(--accent); color: #fff; font-weight: 600;
    border: none; cursor: pointer; font-size: 0.95rem; width: 100%;
  }
  .btn:hover { background: var(--accent-hover); text-decoration: none; }
  .flash { background: var(--red); color: #fff; padding: 0.5rem 1rem;
    border-radius: 6px; margin-bottom: 1rem; font-size: 0.85rem; }

  /* Layout */
  .topbar {
    background: var(--surface); border-bottom: 1px solid var(--border);
    padding: 0.8rem 1.5rem; display: flex; align-items: center;
    justify-content: space-between; position: sticky; top: 0; z-index: 10;
  }
  .topbar h1 { font-size: 1.1rem; font-weight: 600; }
  .topbar .logout { color: var(--text-muted); font-size: 0.85rem; }
  .container { max-width: 1100px; margin: 0 auto; padding: 1.5rem; }

  /* Stats cards */
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem; margin-bottom: 2rem; }
  .stat-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 1.2rem 1.4rem;
  }
  .stat-card .label { font-size: 0.8rem; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.3rem; }
  .stat-card .value { font-size: 1.8rem; font-weight: 700; }
  .stat-card .sub { font-size: 0.8rem; color: var(--text-muted); margin-top: 0.2rem; }

  /* Section */
  .section { margin-bottom: 2rem; }
  .section h2 { font-size: 1.15rem; margin-bottom: 1rem; font-weight: 600; }

  /* Tables */
  .table-wrap {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; overflow: hidden;
  }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; padding: 0.7rem 1rem; font-size: 0.75rem;
    color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em;
    border-bottom: 1px solid var(--border); background: var(--surface2); }
  td { padding: 0.7rem 1rem; border-bottom: 1px solid var(--border); font-size: 0.9rem; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: rgba(108, 140, 255, 0.04); }
  .badge {
    display: inline-block; padding: 0.15rem 0.6rem; border-radius: 99px;
    font-size: 0.75rem; font-weight: 600;
  }
  .badge-green { background: rgba(74, 222, 128, 0.15); color: var(--green); }
  .badge-orange { background: rgba(251, 146, 60, 0.15); color: var(--orange); }
  .badge-muted { background: var(--surface2); color: var(--text-muted); }

  /* Detail card */
  .detail-header { margin-bottom: 1.5rem; }
  .detail-header h2 { font-size: 1.3rem; margin-bottom: 0.3rem; }
  .detail-header .meta { color: var(--text-muted); font-size: 0.85rem; }
  .back-link { display: inline-block; margin-bottom: 1rem; font-size: 0.85rem; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
  @media (max-width: 700px) { .grid-2 { grid-template-columns: 1fr; } }
  .empty { color: var(--text-muted); text-align: center; padding: 2rem; font-size: 0.9rem; }

  /* Questions browser */
  .q-type { font-family: monospace; font-size: 0.8rem; }

  /* Message form */
  .msg-form {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 1.2rem 1.4rem;
  }
  .msg-form label { display: block; font-size: 0.8rem; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.4rem; }
  .msg-form select, .msg-form input[type="number"] {
    width: 100%; padding: 0.55rem 0.8rem; border-radius: 8px;
    border: 1px solid var(--border); background: var(--bg);
    color: var(--text); font-size: 0.9rem; margin-bottom: 0.8rem;
    appearance: auto;
  }
  .msg-form textarea {
    width: 100%; padding: 0.7rem 0.8rem; border-radius: 8px;
    border: 1px solid var(--border); background: var(--bg);
    color: var(--text); font-size: 0.9rem; margin-bottom: 0.8rem;
    min-height: 80px; resize: vertical; font-family: inherit;
  }
  .msg-form select:focus, .msg-form textarea:focus, .msg-form input:focus {
    outline: none; border-color: var(--accent);
  }
  .btn-send { width: auto; padding: 0.55rem 1.5rem; }
  .flash-success { background: rgba(74, 222, 128, 0.15); color: var(--green);
    padding: 0.5rem 1rem; border-radius: 6px; margin-bottom: 1rem; font-size: 0.85rem; }
  .flash-error { background: rgba(248, 113, 113, 0.15); color: var(--red);
    padding: 0.5rem 1rem; border-radius: 6px; margin-bottom: 1rem; font-size: 0.85rem; }
  .topic-hint { font-size: 0.75rem; color: var(--text-muted); margin-top: -0.5rem; margin-bottom: 0.8rem; }
</style>
</head>
<body>

{% if page == 'login' %}
<div class="login-container">
  <div class="login-box">
    <h1>AskUs Bot Dashboard</h1>
    <p>Enter the dashboard password to continue.</p>
    {% for msg in get_flashed_messages() %}
      <div class="flash">{{ msg }}</div>
    {% endfor %}
    <form method="POST">
      <input type="password" name="password" placeholder="Password" autofocus required>
      <button class="btn" type="submit">Sign in</button>
    </form>
  </div>
</div>

{% elif page == 'home' %}
<div class="topbar">
  <h1>AskUs Bot Dashboard</h1>
  <a href="{{ url_for('logout') }}" class="logout">Sign out</a>
</div>
<div class="container">
  <div class="stats">
    <div class="stat-card">
      <div class="label">Active Groups</div>
      <div class="value">{{ stats.groups }}</div>
    </div>
    <div class="stat-card">
      <div class="label">Total Participants</div>
      <div class="value">{{ stats.participants }}</div>
    </div>
    <div class="stat-card">
      <div class="label">Question Templates</div>
      <div class="value">{{ stats.questions }}</div>
    </div>
    <div class="stat-card">
      <div class="label">Questions Asked</div>
      <div class="value">{{ stats.asked }}</div>
      <div class="sub">across all groups</div>
    </div>
  </div>

  <div class="section">
    <h2>Groups</h2>
    {% if groups %}
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Chat ID</th><th>Participants</th><th>Questions Asked</th>
          <th>Remaining</th><th></th>
        </tr></thead>
        <tbody>
          {% for g in groups %}
          <tr>
            <td><code>{{ g.chat_id }}</code></td>
            <td>{{ g.participant_count }}</td>
            <td>{{ g.asked_count }}</td>
            <td>
              {% if g.remaining == 0 %}
                <span class="badge badge-orange">All asked</span>
              {% else %}
                <span class="badge badge-green">{{ g.remaining }} left</span>
              {% endif %}
            </td>
            <td><a href="{{ url_for('group_detail', chat_id=g.chat_id) }}">View details</a></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% else %}
    <div class="table-wrap"><div class="empty">No active groups found.</div></div>
    {% endif %}
  </div>

  <div class="section">
    <h2>Recent Questions Asked</h2>
    {% if recent_asked %}
    <div class="table-wrap">
      <table>
        <thead><tr><th>Chat ID</th><th>Question</th><th>Asked At</th></tr></thead>
        <tbody>
          {% for r in recent_asked %}
          <tr>
            <td><code>{{ r.chat_id }}</code></td>
            <td>{{ r.question_text or r.question_hash }}</td>
            <td>{{ r.asked_at }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% else %}
    <div class="table-wrap"><div class="empty">No questions have been asked yet.</div></div>
    {% endif %}
  </div>

  <div class="section">
    <h2>Send Message as Bot</h2>
    {% for cat, msg in get_flashed_messages(with_categories=true) %}
      <div class="flash-{{ cat }}">{{ msg }}</div>
    {% endfor %}
    <div class="msg-form">
      <form method="POST" action="{{ url_for('send_message') }}">
        <label>Group</label>
        <select name="chat_id" required>
          <option value="">Select a group...</option>
          {% for g in groups %}
          <option value="{{ g.chat_id }}">{{ g.chat_id }} ({{ g.participant_count }} participants)</option>
          {% endfor %}
        </select>
        <label>Topic ID (optional)</label>
        <input type="number" name="topic_id" placeholder="e.g. 2082 for Floooooood">
        <div class="topic-hint">Leave empty to send to the main chat. Use 2082 for the Floooooood topic.</div>
        <label>Message (HTML supported)</label>
        <textarea name="message" placeholder="Type your message here..." required></textarea>
        <button class="btn btn-send" type="submit">Send Message</button>
      </form>
    </div>
  </div>

  <div class="section">
    <h2>Question Templates ({{ stats.questions }})</h2>
    {% if question_templates %}
    <div class="table-wrap">
      <table>
        <thead><tr><th>Question</th><th>Type</th><th>Options</th></tr></thead>
        <tbody>
          {% for q in question_templates %}
          <tr>
            <td>{{ q.question }}</td>
            <td><span class="q-type badge badge-muted">{{ q.type }}</span></td>
            <td>{{ q.options|join(', ') if q.options else '(member names)' }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% else %}
    <div class="table-wrap"><div class="empty">No question templates found.</div></div>
    {% endif %}
  </div>
</div>

{% elif page == 'group' %}
<div class="topbar">
  <h1>AskUs Bot Dashboard</h1>
  <a href="{{ url_for('logout') }}" class="logout">Sign out</a>
</div>
<div class="container">
  <a href="{{ url_for('home') }}" class="back-link">&larr; Back to overview</a>
  <div class="detail-header">
    <h2>Group {{ group.chat_id }}</h2>
    <div class="meta">
      {{ group.participant_count }} participants &middot;
      {{ group.asked_count }} questions asked &middot;
      {{ group.remaining }} remaining
    </div>
  </div>
  <div class="grid-2">
    <div class="section">
      <h2>Participants</h2>
      {% if group.participants %}
      <div class="table-wrap">
        <table>
          <thead><tr><th>Username</th><th>User ID</th><th>Joined</th></tr></thead>
          <tbody>
            {% for p in group.participants %}
            <tr>
              <td>{{ p.username }}</td>
              <td><code>{{ p.user_id }}</code></td>
              <td>{{ p.joined_at }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      {% else %}
      <div class="table-wrap"><div class="empty">No participants.</div></div>
      {% endif %}
    </div>
    <div class="section">
      <h2>Asked Questions</h2>
      {% if group.asked_questions %}
      <div class="table-wrap">
        <table>
          <thead><tr><th>Question</th><th>Asked At</th></tr></thead>
          <tbody>
            {% for a in group.asked_questions %}
            <tr>
              <td>{{ a.question_text or a.question_hash }}</td>
              <td>{{ a.asked_at }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      {% else %}
      <div class="table-wrap"><div class="empty">No questions asked yet.</div></div>
      {% endif %}
    </div>
  </div>

  <div class="section">
    <h2>Send Message to This Group</h2>
    {% for cat, msg in get_flashed_messages(with_categories=true) %}
      <div class="flash-{{ cat }}">{{ msg }}</div>
    {% endfor %}
    <div class="msg-form">
      <form method="POST" action="{{ url_for('send_message') }}">
        <input type="hidden" name="chat_id" value="{{ group.chat_id }}">
        <input type="hidden" name="redirect_to" value="{{ request.path }}">
        <label>Topic ID (optional)</label>
        <input type="number" name="topic_id" placeholder="e.g. 2082 for Floooooood">
        <div class="topic-hint">Leave empty to send to the main chat.</div>
        <label>Message (HTML supported)</label>
        <textarea name="message" placeholder="Type your message here..." required></textarea>
        <button class="btn btn-send" type="submit">Send Message</button>
      </form>
    </div>
  </div>
</div>
{% endif %}

</body>
</html>
"""


# --- Helpers ---
def get_stats():
    total_questions = db["question_templates"].count_documents({})
    total_participants = db["participants"].count_documents({})
    total_asked = db["asked_questions"].count_documents({})
    active_chats = db["participants"].distinct("chat_id")
    return {
        "groups": len(active_chats),
        "participants": total_participants,
        "questions": total_questions,
        "asked": total_asked,
    }


def get_groups_overview():
    chat_ids = db["participants"].distinct("chat_id")
    total_questions = db["question_templates"].count_documents({})
    groups = []
    for cid in chat_ids:
        p_count = db["participants"].count_documents({"chat_id": cid})
        a_count = db["asked_questions"].count_documents({"chat_id": cid})
        remaining = max(0, total_questions - a_count)
        groups.append(
            {
                "chat_id": cid,
                "participant_count": p_count,
                "asked_count": a_count,
                "remaining": remaining,
            }
        )
    groups.sort(key=lambda g: g["participant_count"], reverse=True)
    return groups


def resolve_question_hash(qhash):
    """Try to find the question text for a hash."""
    doc = db["question_templates"].find_one({"hash": qhash}, {"question": 1, "_id": 0})
    return doc["question"] if doc else None


def get_recent_asked(limit=20):
    rows = list(
        db["asked_questions"].find().sort("asked_at", -1).limit(limit)
    )
    results = []
    for r in rows:
        results.append(
            {
                "chat_id": r.get("chat_id"),
                "question_hash": r.get("question_hash", ""),
                "question_text": resolve_question_hash(r.get("question_hash", "")),
                "asked_at": r.get("asked_at", "").strftime("%Y-%m-%d %H:%M")
                if isinstance(r.get("asked_at"), datetime)
                else str(r.get("asked_at", "")),
            }
        )
    return results


def get_question_templates(limit=100):
    return list(
        db["question_templates"]
        .find({}, {"_id": 0, "question": 1, "type": 1, "options": 1})
        .limit(limit)
    )


def get_group_detail(chat_id):
    total_questions = db["question_templates"].count_documents({})
    participants = list(
        db["participants"].find(
            {"chat_id": chat_id}, {"_id": 0, "username": 1, "user_id": 1, "joined_at": 1}
        )
    )
    for p in participants:
        ja = p.get("joined_at")
        if isinstance(ja, datetime):
            p["joined_at"] = ja.strftime("%Y-%m-%d %H:%M")
        elif isinstance(ja, dict):
            p["joined_at"] = "-"
        else:
            p["joined_at"] = str(ja) if ja else "-"

    asked_raw = list(
        db["asked_questions"]
        .find({"chat_id": chat_id})
        .sort("asked_at", -1)
    )
    asked_questions = []
    for a in asked_raw:
        asked_questions.append(
            {
                "question_hash": a.get("question_hash", ""),
                "question_text": resolve_question_hash(a.get("question_hash", "")),
                "asked_at": a.get("asked_at", "").strftime("%Y-%m-%d %H:%M")
                if isinstance(a.get("asked_at"), datetime)
                else str(a.get("asked_at", "")),
            }
        )

    a_count = len(asked_questions)
    return {
        "chat_id": chat_id,
        "participant_count": len(participants),
        "asked_count": a_count,
        "remaining": max(0, total_questions - a_count),
        "participants": participants,
        "asked_questions": asked_questions,
    }


# --- Routes ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pw = request.form.get("password", "")
        if secrets.compare_digest(pw, DASHBOARD_PASSWORD):
            session["authenticated"] = True
            return redirect(url_for("home"))
        flash("Invalid password.")
    return render_template_string(TEMPLATE, page="login")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def home():
    stats = get_stats()
    groups = get_groups_overview()
    recent_asked = get_recent_asked()
    question_templates = get_question_templates()
    return render_template_string(
        TEMPLATE,
        page="home",
        stats=stats,
        groups=groups,
        recent_asked=recent_asked,
        question_templates=question_templates,
    )


@app.route("/group/<int:chat_id>")
@login_required
def group_detail(chat_id):
    group = get_group_detail(chat_id)
    return render_template_string(TEMPLATE, page="group", group=group)


@app.route("/send", methods=["POST"])
@login_required
def send_message():
    chat_id = request.form.get("chat_id", "").strip()
    message = request.form.get("message", "").strip()
    topic_id = request.form.get("topic_id", "").strip() or None
    redirect_to = request.form.get("redirect_to", "").strip()

    if not chat_id or not message:
        flash("Chat ID and message are required.", "error")
        return redirect(redirect_to or url_for("home"))

    ok, desc = telegram_send_message(int(chat_id), message, topic_id)
    if ok:
        flash(f"Message sent to {chat_id}!", "success")
        logger.info("Dashboard sent message to chat %s", chat_id)
    else:
        flash(f"Failed to send: {desc}", "error")
        logger.error("Dashboard failed to send to %s: %s", chat_id, desc)

    return redirect(redirect_to or url_for("home"))


# Also support negative chat IDs (Telegram groups use negative IDs)
@app.route("/group/-<int:chat_id>")
@login_required
def group_detail_negative(chat_id):
    group = get_group_detail(-chat_id)
    return render_template_string(TEMPLATE, page="group", group=group)


# --- Main ---
if __name__ == "__main__":
    if not connect_to_mongodb():
        logger.error("Cannot start dashboard without MongoDB. Exiting.")
        exit(1)

    logger.info("Starting dashboard on port %d", DASHBOARD_PORT)
    logger.info("Login with the DASHBOARD_PASSWORD you set (or check logs above for the generated one)")
    app.run(host="0.0.0.0", port=DASHBOARD_PORT, debug=False)
