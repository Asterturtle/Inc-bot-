"""
GR8Tech Incident Bot
Slack bot that assists L1 support during Critical incidents
with timed escalation reminders and status update templates.
"""

import os
import re
import logging
from datetime import datetime, timezone

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
    build_escalation_message,
    build_status_update_message,
    build_confirmed_message,
    build_stop_summary,
)

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = App(token=os.environ["SLACK_BOT_TOKEN"])

scheduler = BackgroundScheduler()
scheduler.start()

# In-memory state: { user_id: { ticket_key, start_time, jobs[], escalations_triggered, status_updates_sent } }
active_incidents = {}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TICKET_PATTERN = re.compile(r"^[A-Z]+-\d+$")


def get_dm_channel(client, user_id: str) -> str:
    """Open a DM channel with the user and return its ID."""
    result = client.conversations_open(users=[user_id])
    return result["channel"]["id"]


def now_str() -> str:
    """Current time as HH:MM UTC string."""
    return datetime.now(timezone.utc).strftime("%H:%M UTC")


def elapsed_minutes(start_time: datetime) -> int:
    """Minutes elapsed since start_time."""
    return int((datetime.now(timezone.utc) - start_time).total_seconds() / 60)


# ---------------------------------------------------------------------------
# Scheduled job functions
# ---------------------------------------------------------------------------

def send_escalation(client, user_id: str, step_index: int, repeat_count: int = 0):
    """Send an escalation reminder DM. Reschedule repeat if not confirmed."""
    incident = active_incidents.get(user_id)
    if not incident:
        return

    step = ESCALATION_STEPS[step_index]
    ticket_key = incident["ticket_key"]

    channel = get_dm_channel(client, user_id)
    msg = build_escalation_message(ticket_key, step, step_index)

    result = client.chat_postMessage(channel=channel, text=msg["text"], blocks=msg["blocks"])

    # Track message ts so we can update it on confirmation
    incident.setdefault("pending_confirmations", {})[f"escalation_{step_index}"] = {
        "channel": channel,
        "ts": result["ts"],
        "repeat_count": repeat_count,
        "step_index": step_index,
        "type": "escalation",
    }

    incident["escalations_triggered"] = max(
        incident.get("escalations_triggered", 0), step_index + 1
    )

    # Schedule repeat if not confirmed
    if repeat_count < MAX_REPEATS:
        job_id = f"{user_id}_esc_repeat_{step_index}_{repeat_count}"
        job = scheduler.add_job(
            send_escalation,
            "date",
            run_date=datetime.now(timezone.utc).replace(microsecond=0).__add__(
                __import__("datetime").timedelta(seconds=REPEAT_DELAY_SECONDS)
            ),
            args=[client, user_id, step_index, repeat_count + 1],
            id=job_id,
            replace_existing=True,
        )
        incident["jobs"].append(job_id)


def send_status_update(client, user_id: str, repeat_count: int = 0):
    """Send a status update reminder DM with templates."""
    incident = active_incidents.get(user_id)
    if not incident:
        return

    ticket_key = incident["ticket_key"]
    minutes = elapsed_minutes(incident["start_time"])

    channel = get_dm_channel(client, user_id)
    msg = build_status_update_message(ticket_key, minutes)

    result = client.chat_postMessage(channel=channel, text=msg["text"], blocks=msg["blocks"])

    update_key = f"status_{minutes}"
    incident.setdefault("pending_confirmations", {})[update_key] = {
        "channel": channel,
        "ts": result["ts"],
        "repeat_count": repeat_count,
        "type": "status",
        "minutes": minutes,
    }

    incident["status_updates_sent"] = incident.get("status_updates_sent", 0) + 1

    # Schedule repeat if not confirmed
    if repeat_count < MAX_REPEATS:
        job_id = f"{user_id}_status_repeat_{minutes}_{repeat_count}"
        job = scheduler.add_job(
            send_status_update,
            "date",
            run_date=datetime.now(timezone.utc).replace(microsecond=0).__add__(
                __import__("datetime").timedelta(seconds=REPEAT_DELAY_SECONDS)
            ),
            args=[client, user_id, repeat_count + 1],
            id=job_id,
            replace_existing=True,
        )
        incident["jobs"].append(job_id)


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

@app.command("/incident-start")
def handle_incident_start(ack, command, client):
    """Handle /incident-start PSUPINC-12345"""
    ack()

    user_id = command["user_id"]
    text = command.get("text", "").strip()

    # Validate ticket key
    if not text or not TICKET_PATTERN.match(text):
        client.chat_postEphemeral(
            channel=command["channel_id"],
            user=user_id,
            text=":warning: Usage: `/incident-start PSUPINC-12345`\nPlease provide a valid ticket key.",
        )
        return

    # Check for duplicate
    if user_id in active_incidents:
        existing = active_incidents[user_id]["ticket_key"]
        client.chat_postEphemeral(
            channel=command["channel_id"],
            user=user_id,
            text=f":warning: You already have an active incident: *{existing}*\nUse `/incident-stop` first.",
        )
        return

    ticket_key = text.upper()
    start_time = datetime.now(timezone.utc)

    # Initialize incident state
    active_incidents[user_id] = {
        "ticket_key": ticket_key,
        "start_time": start_time,
        "jobs": [],
        "escalations_triggered": 0,
        "status_updates_sent": 0,
        "pending_confirmations": {},
    }

    logger.info(f"Incident started: {ticket_key} by user {user_id}")

    # Send T+0 immediately
    send_escalation(client, user_id, step_index=0)

    # Schedule remaining escalation steps
    from datetime import timedelta

    for i, step in enumerate(ESCALATION_STEPS):
        if i == 0:
            continue  # already sent
        delay = step["minutes"] * 60
        job_id = f"{user_id}_esc_{i}"
        scheduler.add_job(
            send_escalation,
            "date",
            run_date=start_time + timedelta(seconds=delay),
            args=[client, user_id, i],
            id=job_id,
            replace_existing=True,
        )
        active_incidents[user_id]["jobs"].append(job_id)

    # Schedule recurring status updates every 15 minutes
    job_id = f"{user_id}_status"
    scheduler.add_job(
        send_status_update,
        "interval",
        minutes=STATUS_UPDATE_INTERVAL,
        start_date=start_time + timedelta(minutes=STATUS_UPDATE_INTERVAL),
        args=[client, user_id],
        id=job_id,
        replace_existing=True,
    )
    active_incidents[user_id]["jobs"].append(job_id)

    # Confirm to user in channel (ephemeral)
    client.chat_postEphemeral(
        channel=command["channel_id"],
        user=user_id,
        text=f":white_check_mark: Incident timer started for *{ticket_key}*. Check your DMs.",
    )


@app.command("/incident-stop")
def handle_incident_stop(ack, command, client):
    """Handle /incident-stop"""
    ack()

    user_id = command["user_id"]

    if user_id not in active_incidents:
        client.chat_postEphemeral(
            channel=command["channel_id"],
            user=user_id,
            text=":warning: No active incident found. Nothing to stop.",
        )
        return

    incident = active_incidents[user_id]
    ticket_key = incident["ticket_key"]
    duration = elapsed_minutes(incident["start_time"])

    # Cancel all scheduled jobs
    for job_id in incident["jobs"]:
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass  # job may have already fired

    # Send summary DM
    channel = get_dm_channel(client, user_id)
    summary = build_stop_summary(
        ticket_key=ticket_key,
        duration_minutes=duration,
        escalations_triggered=incident.get("escalations_triggered", 0),
        status_updates_sent=incident.get("status_updates_sent", 0),
    )
    client.chat_postMessage(channel=channel, text=summary["text"], blocks=summary["blocks"])

    # Clean up
    del active_incidents[user_id]

    logger.info(f"Incident stopped: {ticket_key} by user {user_id} after {duration} min")

    client.chat_postEphemeral(
        channel=command["channel_id"],
        user=user_id,
        text=f":white_check_mark: Incident *{ticket_key}* stopped. Summary sent to your DMs.",
    )


# ---------------------------------------------------------------------------
# Button handlers
# ---------------------------------------------------------------------------

@app.action(re.compile(r"^(escalation_done_|status_done_)"))
def handle_done_button(ack, body, client):
    """Handle Done button clicks — update the message and cancel repeats."""
    ack()

    user_id = body["user"]["id"]
    action = body["actions"][0]
    action_id = action["action_id"]

    # Update the original message to show confirmation
    channel = body["channel"]["id"]
    message_ts = body["message"]["ts"]

    confirmed = build_confirmed_message(now_str())
    client.chat_update(
        channel=channel,
        ts=message_ts,
        text=confirmed["text"],
        blocks=confirmed["blocks"],
    )

    # Cancel pending repeats for this step
    incident = active_incidents.get(user_id)
    if incident:
        # Remove repeat jobs that match this action
        jobs_to_remove = []
        prefix = action_id.replace("done_", "repeat_").rsplit("_", 1)[0]
        for job_id in incident["jobs"]:
            if prefix.replace("escalation_", "esc_").replace("status_", "status_") in job_id and "repeat" in job_id:
                try:
                    scheduler.remove_job(job_id)
                except Exception:
                    pass
                jobs_to_remove.append(job_id)
        for job_id in jobs_to_remove:
            incident["jobs"].remove(job_id)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Use Socket Mode — no public URL needed
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    logger.info("⚡ Incident Bot is running (Socket Mode)")
    handler.start()
