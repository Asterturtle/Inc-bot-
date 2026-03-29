"""
GR8Tech Incident Bot v5
- No ticket key needed
- Everything in DM with bot
- Stop button in every message
- App Home with Start button
- Next step countdown
- Auto-cleanup: deletes all bot messages on stop, keeps only summary
"""

import os
import re
import logging
from datetime import datetime, timezone, timedelta

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from apscheduler.schedulers.background import BackgroundScheduler

from escalation import (
    ESCALATION_STEPS,
    STATUS_UPDATE_INTERVAL,
    MAX_REPEATS,
    REPEAT_DELAY_SECONDS,
)
from messages import (
    build_app_home,
    build_escalation_message,
    build_status_update_message,
    build_confirmed_message,
    build_stop_summary,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = App(token=os.environ["SLACK_BOT_TOKEN"])

scheduler = BackgroundScheduler()
scheduler.start()

active_incidents = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_dm_channel(client, user_id: str) -> str:
    result = client.conversations_open(users=[user_id])
    return result["channel"]["id"]


def now_str() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M UTC")


def elapsed_minutes(start_time: datetime) -> int:
    return int((datetime.now(timezone.utc) - start_time).total_seconds() / 60)


def track_message(user_id: str, channel: str, ts: str):
    """Track a bot message so we can delete it later."""
    incident = active_incidents.get(user_id)
    if incident:
        incident.setdefault("sent_messages", []).append({"channel": channel, "ts": ts})


def delete_all_messages(client, user_id: str):
    """Delete all tracked bot messages for this incident."""
    incident = active_incidents.get(user_id)
    if not incident:
        return
    for msg in incident.get("sent_messages", []):
        try:
            client.chat_delete(channel=msg["channel"], ts=msg["ts"])
        except Exception:
            pass  # message may already be deleted


def update_home(client, user_id: str):
    incident = active_incidents.get(user_id)
    if incident:
        blocks = build_app_home(
            has_active_incident=True,
            duration_minutes=elapsed_minutes(incident["start_time"]),
        )
    else:
        blocks = build_app_home(has_active_incident=False)
    client.views_publish(user_id=user_id, view={"type": "home", "blocks": blocks})


def start_incident(client, user_id: str) -> bool:
    if user_id in active_incidents:
        return False

    start_time = datetime.now(timezone.utc)
    active_incidents[user_id] = {
        "start_time": start_time,
        "jobs": [],
        "escalations_triggered": 0,
        "status_updates_sent": 0,
        "pending_confirmations": {},
        "sent_messages": [],
    }

    logger.info(f"Incident started by user {user_id}")

    send_escalation(client, user_id, step_index=0)

    for i, step in enumerate(ESCALATION_STEPS):
        if i == 0:
            continue
        job_id = f"{user_id}_esc_{i}"
        scheduler.add_job(
            send_escalation, "date",
            run_date=start_time + timedelta(seconds=step["minutes"] * 60),
            args=[client, user_id, i],
            id=job_id, replace_existing=True,
        )
        active_incidents[user_id]["jobs"].append(job_id)

    job_id = f"{user_id}_status"
    scheduler.add_job(
        send_status_update, "interval",
        minutes=STATUS_UPDATE_INTERVAL,
        start_date=start_time + timedelta(minutes=STATUS_UPDATE_INTERVAL),
        args=[client, user_id],
        id=job_id, replace_existing=True,
    )
    active_incidents[user_id]["jobs"].append(job_id)

    update_home(client, user_id)
    return True


def stop_incident(client, user_id: str) -> dict | None:
    if user_id not in active_incidents:
        return None
    incident = active_incidents[user_id]
    duration = elapsed_minutes(incident["start_time"])

    for job_id in incident["jobs"]:
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass

    # Delete all bot messages from the DM
    delete_all_messages(client, user_id)

    summary_data = {
        "duration_minutes": duration,
        "escalations_triggered": incident.get("escalations_triggered", 0),
        "status_updates_sent": incident.get("status_updates_sent", 0),
    }
    del active_incidents[user_id]
    logger.info(f"Incident stopped by user {user_id} after {duration} min")

    update_home(client, user_id)
    return summary_data


# ---------------------------------------------------------------------------
# Scheduled jobs
# ---------------------------------------------------------------------------

def send_escalation(client, user_id: str, step_index: int, repeat_count: int = 0):
    incident = active_incidents.get(user_id)
    if not incident:
        return

    step = ESCALATION_STEPS[step_index]
    channel = get_dm_channel(client, user_id)
    msg = build_escalation_message(step, step_index)

    result = client.chat_postMessage(channel=channel, text=msg["text"], blocks=msg["blocks"])
    track_message(user_id, channel, result["ts"])

    incident.setdefault("pending_confirmations", {})[f"escalation_{step_index}"] = {
        "channel": channel, "ts": result["ts"], "repeat_count": repeat_count,
    }
    incident["escalations_triggered"] = max(
        incident.get("escalations_triggered", 0), step_index + 1
    )

    if repeat_count < MAX_REPEATS:
        job_id = f"{user_id}_esc_repeat_{step_index}_{repeat_count}"
        scheduler.add_job(
            send_escalation, "date",
            run_date=datetime.now(timezone.utc) + timedelta(seconds=REPEAT_DELAY_SECONDS),
            args=[client, user_id, step_index, repeat_count + 1],
            id=job_id, replace_existing=True,
        )
        incident["jobs"].append(job_id)


def send_status_update(client, user_id: str, repeat_count: int = 0):
    incident = active_incidents.get(user_id)
    if not incident:
        return

    minutes = elapsed_minutes(incident["start_time"])
    channel = get_dm_channel(client, user_id)
    msg = build_status_update_message(minutes)

    result = client.chat_postMessage(channel=channel, text=msg["text"], blocks=msg["blocks"])
    track_message(user_id, channel, result["ts"])

    incident.setdefault("pending_confirmations", {})[f"status_{minutes}"] = {
        "channel": channel, "ts": result["ts"], "repeat_count": repeat_count,
    }
    incident["status_updates_sent"] = incident.get("status_updates_sent", 0) + 1

    if repeat_count < MAX_REPEATS:
        job_id = f"{user_id}_status_repeat_{minutes}_{repeat_count}"
        scheduler.add_job(
            send_status_update, "date",
            run_date=datetime.now(timezone.utc) + timedelta(seconds=REPEAT_DELAY_SECONDS),
            args=[client, user_id, repeat_count + 1],
            id=job_id, replace_existing=True,
        )
        incident["jobs"].append(job_id)


# ---------------------------------------------------------------------------
# App Home
# ---------------------------------------------------------------------------

@app.event("app_home_opened")
def handle_app_home_opened(client, event):
    user_id = event["user"]
    update_home(client, user_id)


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

@app.command("/incident-start")
def handle_incident_start(ack, command, client):
    ack()
    user_id = command["user_id"]
    channel = get_dm_channel(client, user_id)

    if not start_incident(client, user_id):
        client.chat_postMessage(
            channel=channel,
            text=":warning: You already have an active incident. Press *Stop* or use `/incident-stop` first.",
        )


@app.command("/incident-stop")
def handle_incident_stop(ack, command, client):
    ack()
    user_id = command["user_id"]
    channel = get_dm_channel(client, user_id)

    summary_data = stop_incident(client, user_id)
    if not summary_data:
        client.chat_postMessage(channel=channel, text=":warning: No active incident. Nothing to stop.")
        return

    summary = build_stop_summary(**summary_data)
    client.chat_postMessage(channel=channel, text=summary["text"], blocks=summary["blocks"])


# ---------------------------------------------------------------------------
# Button handlers
# ---------------------------------------------------------------------------

@app.action("start_incident")
def handle_start_button(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    channel = get_dm_channel(client, user_id)

    if not start_incident(client, user_id):
        client.chat_postMessage(
            channel=channel,
            text=":warning: You already have an active incident. Press *Stop* or use `/incident-stop` first.",
        )


@app.action(re.compile(r"^(escalation_done_|status_done_)"))
def handle_done_button(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    channel = body["channel"]["id"]
    message_ts = body["message"]["ts"]

    confirmed = build_confirmed_message(now_str())
    client.chat_update(channel=channel, ts=message_ts, text=confirmed["text"], blocks=confirmed["blocks"])

    incident = active_incidents.get(user_id)
    if incident:
        jobs_to_remove = []
        for job_id in incident["jobs"]:
            if "repeat" in job_id:
                try:
                    scheduler.remove_job(job_id)
                except Exception:
                    pass
                jobs_to_remove.append(job_id)
        for job_id in jobs_to_remove:
            if job_id in incident["jobs"]:
                incident["jobs"].remove(job_id)


@app.action("stop_incident")
def handle_stop_button(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    channel = get_dm_channel(client, user_id)

    summary_data = stop_incident(client, user_id)
    if not summary_data:
        client.chat_postMessage(channel=channel, text=":warning: No active incident. Already stopped.")
        return

    summary = build_stop_summary(**summary_data)
    client.chat_postMessage(channel=channel, text=summary["text"], blocks=summary["blocks"])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    logger.info("⚡ Incident Bot is running (Socket Mode)")
    handler.start()
