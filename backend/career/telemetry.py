"""Server-side telemetry to PostHog: application health events (searches,
drafts, AI failures, alert delivery, backend exceptions) sent fire-and-forget.

Events carry counts, durations and error types only; never CV text, postings,
drafts, emails or keys. Members are identified by their account ID, the same
distinct ID the dashboard uses, so browser and server events line up in one
person timeline. Off unless POSTHOG_KEY is set."""

import logging
import threading
import traceback
from datetime import datetime, timezone
import httpx
from .config import settings
from .db import current_user

log = logging.getLogger(__name__)
LIB = "career-pilot-server"


def enabled():
    return bool(settings.posthog_key and settings.posthog_server_events)


def _post(payload):
    try:
        httpx.post(settings.posthog_host.rstrip("/") + "/capture/", json=payload, timeout=10)
    except Exception:
        log.debug("telemetry send failed", exc_info=True)


def capture(event, properties=None, distinct_id="server"):
    if not enabled():
        return
    props = {"$lib": LIB, "$process_person_profile": distinct_id not in (None, "server"), **(properties or {})}
    organisation = (current_user() or {}).get("organisation")
    if organisation and distinct_id not in (None, "server"):
        # Group analytics: the member's institution or cohort.
        props.setdefault("$groups", {"organisation": organisation})
    payload = {
        "api_key": settings.posthog_key,
        "event": event,
        "distinct_id": distinct_id or "server",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "properties": props,
    }
    threading.Thread(target=_post, args=(payload,), daemon=True).start()


def capture_exception(exc, distinct_id="server", **properties):
    """Report a backend exception to PostHog error tracking (type and a trimmed
    stack; no request bodies or personal data)."""
    if not enabled():
        return
    frames = traceback.extract_tb(exc.__traceback__)[-8:] if exc.__traceback__ else []
    capture(
        "$exception",
        {
            "$exception_list": [
                {
                    "type": type(exc).__name__,
                    "value": str(exc)[:300],
                    "mechanism": {"handled": True},
                    "stacktrace": {
                        "type": "raw",
                        "frames": [
                            {"filename": f.filename.split("/")[-1].split("\\\\")[-1], "function": f.name, "lineno": f.lineno, "in_app": "career" in f.filename}
                            for f in frames
                        ],
                    },
                }
            ],
            **properties,
        },
        distinct_id=distinct_id,
    )
