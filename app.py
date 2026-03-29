"""
GR8Tech Incident Bot v7
- Persistent control panel (one message, updates in place)
- Compact progress bar in escalation/status messages
- Detailed progress in /incident-status & Status button
- Pause/Resume, Extend +5 min
- Auto-cleanup on stop
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
    build_control_panel,
    build_escalation_message,
    build_status_update_message,
    build_status_view,
    build_confirmed_message,
    build_stop_summary,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = App(token=os.environ["SLACK_BOT_TOKEN"])

scheduler = BackgroundScheduler()
scheduler.start()

active_incidents = {}

EXTEND_MINUTES = 5


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


def get_current_step(incident: dict) -> int:
    minutes = elapsed_minutes(incident["start_time"])
    current = 0
    for i, step in enumerate(ESCALATION_STEPS):
        if minutes >= step["minutes"]:
            current = i
    return current


def track_message(user_id: str, channel: str, ts: str):
    incident = active_incidents.get(user_id)
    if incident:
        incident.setdefault("sent_messages", []).append({"channel": channel, "ts": ts})


def delete_all_messages(client, user_id: str):
    incident = active_incidents.get(user_id)
    if not incident:
        return
    for msg in incident.get("sent_messages", []):
        try:
            client.chat_delete(channel=msg["channel"], ts=msg["ts"])
        except Exception:
            pass
    # Also delete control panel
    panel = incident.get("panel")
    if panel:
        try:
            client.chat_delete(channel=panel["channel"], ts=panel["ts"])
        except Exception:
            pass


def refresh_panel(client, user_id: str):
    """Update the control panel message in place."""
    incident = active_incidents.get(user_id)
    if not incident or not incident.get("panel"):
        return

    panel = incident["panel"]
    minutes = elapsed_minutes(incident["start_time"])
    current_step = get_current_step(incident)

    msg = build_control_panel(
        elapsed_min=minutes,
        current_step=current_step,
        is_paused=incident.get("paused", False),
    )

    try:
        client.chat_update(
            channel=panel["channel"],
            ts=panel["ts"],
            text=msg["text"],
            blocks=msg["blocks"],
        )
    except Exception:
        pass


def update_home(client, user_id: str):
    incident = active_incidents.get(user_id)
    if incident:
        blocks = build_app_home(
            has_active_incident=True,
            duration_minutes=elapsed_minutes(incident["start_time"]),
            is_paused=incident.get("paused", False),
            current_step=get_current_step(incident),
        )
    else:
        blocks = build_app_home(has_active_incident=False)
    client.views_publish(user_id=user_id, view={"type": "home", "blocks": blocks})


def send_control_panel(client, user_id: str):
    """Send the initial control panel and store its ts for updates."""
    incident = active_incidents.get(user_id)
    if not incident:
        return

    channel = get_dm_channel(client, user_id)
    msg = build_control_panel(
        elapsed_min=0,
        current_step=0,
        is_paused=False,
    )

    result = client.chat_postMessage(channel=channel, text=msg["text"], blocks=msg["blocks"])
    incident["panel"] = {"channel": channel, "ts": result["ts"]}


# ---------------------------------------------------------------------------
# Core actions
# ---------------------------------------------------------------------------

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
        "panel": None,
        "paused": False,
        "paused_jobs": [],
    }

    logger.info(f"Incident started by user {user_id}")

    # Send control panel first
    send_control_panel(client, user_id)

    # Send T+0 escalation
    send_escalation(client, user_id, step_index=0)

    # Schedule remaining escalation steps
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

    # Schedule status updates
    job_id = f"{user_id}_status"
    scheduler.add_job(
        send_status_update, "interval",
        minutes=STATUS_UPDATE_INTERVAL,
        start_date=start_time + timedelta(minutes=STATUS_UPDATE_INTERVAL),
        args=[client, user_id],
        id=job_id, replace_existing=True,
    )
    active_incidents[user_id]["jobs"].append(job_id)

    # Schedule panel refresh every minute to keep elapsed time current
    panel_job = f"{user_id}_panel_refresh"
    scheduler.add_job(
        refresh_panel, "interval",
        minutes=1,
        args=[client, user_id],
        id=panel_job, replace_existing=True,
    )
    active_incidents[user_id]["jobs"].append(panel_job)

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


def pause_incident(client, user_id: str) -> bool:
    incident = active_incidents.get(user_id)
    if not incident or incident.get("paused"):
        return False

    paused_info = []
    for job_id in incident["jobs"]:
        if "panel_refresh" in job_id:
            continue  # keep panel refresh running
        try:
            job = scheduler.get_job(job_id)
            if job and job.next_run_time:
                remaining = (job.next_run_time - datetime.now(timezone.utc)).total_seconds()
                paused_info.append({"job_id": job_id, "remaining_seconds": max(remaining, 0)})
                scheduler.pause_job(job_id)
        except Exception:
            pass

    incident["paused"] = True
    incident["paused_jobs"] = paused_info
    refresh_panel(client, user_id)
    update_home(client, user_id)
    return True


def resume_incident(client, user_id: str) -> bool:
    incident = active_incidents.get(user_id)
    if not incident or not incident.get("paused"):
        return False

    now = datetime.now(timezone.utc)
    for info in incident.get("paused_jobs", []):
        try:
            job = scheduler.get_job(info["job_id"])
            if job:
                new_run_time = now + timedelta(seconds=info["remaining_seconds"])
                scheduler.reschedule_job(info["job_id"], trigger="date", run_date=new_run_time)
                scheduler.resume_job(info["job_id"])
        except Exception:
            pass

    incident["paused"] = False
    incident["paused_jobs"] = []
    refresh_panel(client, user_id)
    update_home(client, user_id)
    return True


def extend_incident(client, user_id: str, extra_minutes: int = 5) -> bool:
    incident = active_incidents.get(user_id)
    if not incident:
        return False

    extra = timedelta(minutes=extra_minutes)
    for job_id in incident["jobs"]:
        if "_esc_" in job_id and "repeat" not in job_id and "panel" not in job_id:
            try:
                job = scheduler.get_job(job_id)
                if job and job.next_run_time:
                    scheduler.reschedule_job(job_id, trigger="date", run_date=job.next_run_time + extra)
            except Exception:
                pass

    refresh_panel(client, user_id)
    return True


# ---------------------------------------------------------------------------
# Scheduled jobs
# ---------------------------------------------------------------------------

def send_escalation(client, user_id: str, step_index: int, repeat_count: int = 0):
    incident = active_incidents.get(user_id)
    if not incident or incident.get("paused"):
        return

    step = ESCALATION_STEPS[step_index]
    channel = get_dm_channel(client, user_id)
    msg = build_escalation_message(step, step_index)

    result = client.chat_postMessage(channel=channel, text=msg["text"], blocks=msg["blocks"])
    track_message(user_id, channel, result["ts"])

    incident["escalations_triggered"] = max(
        incident.get("escalations_triggered", 0), step_index + 1
    )

    # Refresh panel to show updated step
    refresh_panel(client, user_id)

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
    if not incident or incident.get("paused"):
        return

    minutes = elapsed_minutes(incident["start_time"])
    channel = get_dm_channel(client, user_id)
    msg = build_status_update_message(minutes)

    result = client.chat_postMessage(channel=channel, text=msg["text"], blocks=msg["blocks"])
    track_message(user_id, channel, result["ts"])

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
    tab = event.get("tab", "home")

    if tab == "home":
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
        client.chat_postMessage(channel=channel, text=":warning: You already have an active incident. Press *Stop* first.")


@app.command("/incident-stop")
def handle_incident_stop(ack, command, client):
    ack()
    user_id = command["user_id"]
    channel = get_dm_channel(client, user_id)

    summary_data = stop_incident(client, user_id)
    if not summary_data:
        client.chat_postMessage(channel=channel, text=":warning: No active incident.")
        return

    summary = build_stop_summary(**summary_data)
    client.chat_postMessage(channel=channel, text=summary["text"], blocks=summary["blocks"])


@app.command("/incident-status")
def handle_incident_status(ack, command, client):
    ack()
    user_id = command["user_id"]
    channel = get_dm_channel(client, user_id)

    incident = active_incidents.get(user_id)
    if not incident:
        client.chat_postMessage(channel=channel, text=":warning: No active incident.")
        return

    msg = build_status_view(
        elapsed_min=elapsed_minutes(incident["start_time"]),
        current_step=get_current_step(incident),
        escalations_triggered=incident.get("escalations_triggered", 0),
        status_updates_sent=incident.get("status_updates_sent", 0),
        is_paused=incident.get("paused", False),
    )
    result = client.chat_postMessage(channel=channel, text=msg["text"], blocks=msg["blocks"])
    track_message(user_id, channel, result["ts"])


# ---------------------------------------------------------------------------
# Button handlers
# ---------------------------------------------------------------------------

@app.action("start_incident")
def handle_start_button(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    channel = get_dm_channel(client, user_id)

    if not start_incident(client, user_id):
        client.chat_postMessage(channel=channel, text=":warning: You already have an active incident. Press *Stop* first.")


@app.action(re.compile(r"^(escalation_done_|status_done_)"))
def handle_done_button(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    channel = body["channel"]["id"]
    message_ts = body["message"]["ts"]
    action = body["actions"][0]
    description = action.get("value", "")

    confirmed = build_confirmed_message(now_str(), description)
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
        for jid in jobs_to_remove:
            if jid in incident["jobs"]:
                incident["jobs"].remove(jid)


@app.action("stop_incident")
def handle_stop_button(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    channel = get_dm_channel(client, user_id)

    summary_data = stop_incident(client, user_id)
    if not summary_data:
        client.chat_postMessage(channel=channel, text=":warning: No active incident.")
        return

    summary = build_stop_summary(**summary_data)
    client.chat_postMessage(channel=channel, text=summary["text"], blocks=summary["blocks"])


@app.action("pause_incident")
def handle_pause_button(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    channel = get_dm_channel(client, user_id)

    if not pause_incident(client, user_id):
        client.chat_postMessage(channel=channel, text=":warning: Nothing to pause.")


@app.action("resume_incident")
def handle_resume_button(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    channel = get_dm_channel(client, user_id)

    if not resume_incident(client, user_id):
        client.chat_postMessage(channel=channel, text=":warning: Incident is not paused.")


@app.action("extend_incident")
def handle_extend_button(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    channel = get_dm_channel(client, user_id)

    if extend_incident(client, user_id, EXTEND_MINUTES):
        msg = f":clock3: Next escalation extended by {EXTEND_MINUTES} minutes."
        result = client.chat_postMessage(channel=channel, text=msg)
        track_message(user_id, channel, result["ts"])
    else:
        client.chat_postMessage(channel=channel, text=":warning: No active incident.")


@app.action("show_status")
def handle_status_button(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    channel = get_dm_channel(client, user_id)

    incident = active_incidents.get(user_id)
    if not incident:
        client.chat_postMessage(channel=channel, text=":warning: No active incident.")
        return

    msg = build_status_view(
        elapsed_min=elapsed_minutes(incident["start_time"]),
        current_step=get_current_step(incident),
        escalations_triggered=incident.get("escalations_triggered", 0),
        status_updates_sent=incident.get("status_updates_sent", 0),
        is_paused=incident.get("paused", False),
    )
    result = client.chat_postMessage(channel=channel, text=msg["text"], blocks=msg["blocks"])
    track_message(user_id, channel, result["ts"])


@app.action("clear_chat")
def handle_clear_chat(ack, body, client):
    """Delete ALL bot messages from the DM — full cleanup using conversation history."""
    ack()
    user_id = body["user"]["id"]
    channel = get_dm_channel(client, user_id)

    # Get bot's own user ID
    bot_info = client.auth_test()
    bot_user_id = bot_info["user_id"]

    # Read conversation history and delete all bot messages
    cursor = None
    deleted = 0
    while True:
        kwargs = {"channel": channel, "limit": 100}
        if cursor:
            kwargs["cursor"] = cursor

        result = client.conversations_history(**kwargs)

        for msg in result.get("messages", []):
            # Only delete messages from the bot, skip the control panel
            incident = active_incidents.get(user_id)
            panel_ts = incident["panel"]["ts"] if incident and incident.get("panel") else None

            if msg.get("user") == bot_user_id or msg.get("bot_id"):
                if panel_ts and msg["ts"] == panel_ts:
                    continue  # keep the control panel
                try:
                    client.chat_delete(channel=channel, ts=msg["ts"])
                    deleted += 1
                except Exception:
                    pass

        # Check for more pages
        cursor = result.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    # Clear tracked messages
    incident = active_incidents.get(user_id)
    if incident:
        incident["sent_messages"] = []

    logger.info(f"Chat cleared for user {user_id}: {deleted} messages deleted")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    logger.info("⚡ Incident Bot v7 is running (Socket Mode)")
    handler.start()
