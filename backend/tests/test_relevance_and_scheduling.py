from datetime import datetime, timezone, timedelta
from career.relevance import keyword_hits, screen, location_match, priority
from career.db import Session, Record, put, read, now
from career.config import settings
from career import scheduler, telegram


PREFS = {
    "keywords": ["data science", "machine learning", "climate", "hydrology", "digital agriculture"],
    "locations": ["Ethiopia", "Remote", "Africa"],
    "excluded_keywords": ["sales"],
    "location_mode": "soft",
}


def test_keyword_stems_match_inflections():
    assert keyword_hits("Senior Data Scientist wanted", ["data science"]) == ["data science"]
    assert keyword_hits("Hydrological modelling role", ["hydrology"]) == ["hydrology"]
    assert keyword_hits("Climatic risk analyst", ["climate"]) == ["climate"]
    assert keyword_hits("Agricultural digitalisation lead", ["digital agriculture"]) == ["digital agriculture"]
    assert keyword_hits("Accountant", ["data science", "GIS"]) == []
    assert keyword_hits("GIS Officer", ["GIS"]) == ["GIS"]
    assert keyword_hits("Registrar", ["GIS"]) == []
    # Multi-word keywords must occur as a phrase, not as scattered words.
    assert keyword_hits("Remote role handling sensitive data", ["remote sensing"]) == []
    assert keyword_hits("Remote-sensing and earth observation analyst", ["remote sensing"]) == ["remote sensing"]
    assert keyword_hits("Senior Golang developer; some data reporting", ["data science"]) == []
    assert keyword_hits("Data and Science Officer", ["data science"]) == ["data science"]
    assert keyword_hits("Learning platform for machines", ["machine learning"]) == []


def test_screen_and_locations():
    job = {"title": "Data Scientist", "description": "Climate models.", "location": "Addis Ababa, Ethiopia"}
    verdict = screen(job, PREFS)
    assert verdict["keep"] and verdict["title_hits"] == ["data science"] and verdict["location_match"]
    assert not screen({**job, "description": "Sales role with climate models."}, PREFS)["keep"]
    assert not screen({"title": "Chef", "description": "Cooking.", "location": "Ethiopia"}, PREFS)["keep"]
    assert location_match("Nairobi, Kenya", ["Africa"]) and location_match("Remote, Worldwide", ["Remote"])
    assert not location_match("Geneva, Switzerland", ["Ethiopia", "Remote"])
    assert location_match("Not specified", ["Ethiopia"])
    strict = {**PREFS, "location_mode": "strict"}
    assert not screen({**job, "location": "Geneva"}, strict)["keep"]
    assert screen({**job, "location": "Geneva"}, PREFS)["keep"]


def test_priority_prefers_title_hits_and_recency():
    a = {"screen": {"title_hits": ["x"], "location_match": True}, "posted": "2026-09-01T00:00:00+00:00"}
    b = {"screen": {"title_hits": [], "location_match": True}, "posted": "2026-09-18T00:00:00+00:00"}
    c = {"screen": {"title_hits": ["x"], "location_match": True}, "posted": "2026-09-18T00:00:00+00:00"}
    assert sorted([a, b, c], key=priority) == [c, a, b]


def test_schedule_due_logic(client, owner_scope):
    with Session() as db:
        assert not scheduler.due(db)
        put(db, "schedule", "schedule", {"enabled": True})
        assert scheduler.due(db)
        put(db, "run", "run:recent", {"status": "completed", "created": now()})
        assert not scheduler.due(db)
        old = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
        put(db, "run", "run:recent", {"status": "completed", "created": old})
        assert scheduler.due(db)
        put(db, "preferences", "preferences", {"scan_interval_hours": 12})
        assert not scheduler.due(db)
        put(db, "run", "run:busy", {"status": "running", "created": now()})
        put(db, "preferences", "preferences", {"scan_interval_hours": 1})
        assert not scheduler.due(db)


def test_stale_runs_and_preparations_are_repaired(client):
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    with Session() as db:
        put(db, "run", "run:stale", {"status": "running", "created": old})
        put(db, "run", "run:fresh", {"status": "running", "created": now()})
        put(db, "application", "application:x", {"status": "preparing", "approved_at": old})
    scheduler.repair_stale_runs()
    with Session() as db:
        assert read(db, "run:stale")["status"] == "interrupted"
        assert read(db, "run:fresh")["status"] == "running"
        assert read(db, "application:x")["status"] == "failed"


def test_telegram_linking_only_accepts_fresh_code(client, owner_scope, monkeypatch):
    sent = []
    monkeypatch.setattr(telegram, "api", lambda method, **p: sent.append((method, p)) or {})
    with Session() as db:
        code = telegram.create_link_code(db)
        telegram.handle_message(db, {"chat": {"id": 555, "type": "private"}, "from": {"username": "stranger"}, "text": "WRONG"})
        assert not read(db, "telegram") and not sent
        telegram.handle_message(db, {"chat": {"id": 42, "type": "group"}, "from": {}, "text": code})
        assert not read(db, "telegram")
        telegram.handle_message(db, {"chat": {"id": 777, "type": "private"}, "from": {"username": "owner"}, "text": "/start " + code.lower()})
        assert read(db, "telegram")["chat_id"] == "777" and read(db, "telegram_link") is None
        assert sent[-1][0] == "sendMessage" and sent[-1][1]["chat_id"] == "777"
        assert telegram.link_status(db)["linked"]


def test_telegram_callback_requires_linked_chat(client, owner_scope, monkeypatch):
    calls = []
    monkeypatch.setattr(telegram, "api", lambda method, **p: calls.append(method) or {})
    with Session() as db:
        job = put(db, "job", "job:t", {"title": "T", "status": "new"})
        put(db, "telegram", "telegram", {"chat_id": "777"})
        telegram.handle_callback(db, {"id": "1", "from": {"id": 999}, "message": {"chat": {"id": 777}}, "data": "save:" + job.id})
        assert read(db, "job:t")["status"] == "new" and not calls
        telegram.handle_callback(db, {"id": "1", "from": {"id": 777}, "message": {"chat": {"id": 777}, "message_id": 5}, "data": "save:" + job.id})
        assert read(db, "job:t")["status"] == "saved" and "answerCallbackQuery" in calls
        telegram.handle_callback(db, {"id": "2", "from": {"id": 777}, "message": {"chat": {"id": 777}}, "data": "skip:" + job.id})
        assert read(db, "job:t")["status"] == "skipped"


def test_telegram_link_endpoints(client, monkeypatch):
    assert client.post("/api/telegram/link").status_code == 409
    monkeypatch.setattr(settings, "telegram_bot_token", "token")
    monkeypatch.setattr(telegram, "bot_username", lambda: "career_bot")
    r = client.post("/api/telegram/link").json()
    assert len(r["code"]) == 6 and r["bot_username"] == "career_bot" and not r["linked"]
    assert client.get("/api/state").json()["telegram"]["bot_configured"]
    assert client.delete("/api/telegram/link").json()["linked"] is False
