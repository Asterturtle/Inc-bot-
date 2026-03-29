"""
Slack Block Kit message builders v4.
- No ticket key
- Stop button in every message
- App Home with Start button
- Next step countdown in every message
"""

from escalation import CLIENT_TEMPLATE, INTERNAL_TEMPLATE, ESCALATION_STEPS, STATUS_UPDATE_INTERVAL


def _stop_button():
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": "Stop incident"},
        "style": "danger",
        "action_id": "stop_incident",
        "confirm": {
            "title": {"type": "plain_text", "text": "Stop incident?"},
            "text": {"type": "mrkdwn", "text": "This will cancel all timers and end the incident."},
            "confirm": {"type": "plain_text", "text": "Yes, stop"},
            "deny": {"type": "plain_text", "text": "Cancel"},
        },
    }


def _next_step_text(step_index: int) -> str:
    """Build 'Next: ...' text based on current step."""
    current = ESCALATION_STEPS[step_index]
    current_min = current["minutes"]

    # Find next escalation step
    next_esc = None
    for s in ESCALATION_STEPS:
        if s["minutes"] > current_min:
            next_esc = s
            break

    # Find next status update
    # Status updates happen at 15, 30, 45, ...
    # Find the first one after current_min
    next_status_min = STATUS_UPDATE_INTERVAL
    while next_status_min <= current_min:
        next_status_min += STATUS_UPDATE_INTERVAL

    parts = []

    if next_esc:
        mins_until_esc = next_esc["minutes"] - current_min
        who = next_esc["notify"] or next_esc["optional"]
        parts.append(f":arrow_right: Next escalation: *{who}* — in {mins_until_esc} min")

    mins_until_status = next_status_min - current_min
    parts.append(f":clipboard: Next status update in {mins_until_status} min")

    return "\n".join(parts)


def _next_status_text(elapsed_minutes: int) -> str:
    """Build 'Next: ...' text for status update messages."""
    # Find next escalation step after current elapsed time
    next_esc = None
    for s in ESCALATION_STEPS:
        if s["minutes"] > elapsed_minutes:
            next_esc = s
            break

    parts = []

    if next_esc:
        mins_until = next_esc["minutes"] - elapsed_minutes
        who = next_esc["notify"] or next_esc["optional"]
        parts.append(f":arrow_right: Next escalation: *{who}* — in {mins_until} min")

    parts.append(f":clipboard: Next status update in {STATUS_UPDATE_INTERVAL} min")

    return "\n".join(parts)


def build_app_home(has_active_incident: bool = False, duration_minutes: int = 0) -> list:
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":rotating_light: GR8Tech Incident Bot"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "Assists L1 support during Critical incidents with timed escalation reminders and status update templates."},
        },
        {"type": "divider"},
    ]

    if has_active_incident:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":red_circle: *Incident active* — {duration_minutes} min elapsed"},
        })
        blocks.append({
            "type": "actions",
            "elements": [_stop_button()],
        })
    else:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":large_green_circle: *No active incident*"},
        })
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Start incident"},
                    "style": "primary",
                    "action_id": "start_incident",
                },
            ],
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": "You can also use `/incident-start` and `/incident-stop` commands."},
        ],
    })

    return blocks


def build_escalation_message(step: dict, step_index: int) -> dict:
    title = f":rotating_light: {step['title']}"

    notify_lines = []
    if step["notify"]:
        notify_lines.append(f"*Notify: {step['notify']}*")
    if step["optional"]:
        notify_lines.append(f"_{step['optional']}_")

    notify_text = "\n".join(notify_lines) if notify_lines else "_No mandatory notification at this step_"

    next_text = _next_step_text(step_index)

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": title}},
        {"type": "section", "text": {"type": "mrkdwn", "text": notify_text}},
        {"type": "divider"},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": next_text}]},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Done"},
                    "style": "primary",
                    "action_id": f"escalation_done_{step_index}",
                },
                _stop_button(),
            ],
        },
    ]

    return {"text": step["title"], "blocks": blocks}


def build_status_update_message(elapsed_minutes: int) -> dict:
    header = f":memo: {elapsed_minutes} min elapsed — time for status update"

    client_text = CLIENT_TEMPLATE.replace("{{text}}", "_<your text here>_")
    internal_text = INTERNAL_TEMPLATE.replace("{{text}}", "_<your text here>_")

    next_text = _next_status_text(elapsed_minutes)

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Client update:*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"```{client_text}```"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Internal update:*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"```{internal_text}```"}},
        {"type": "divider"},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": next_text}]},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Done"},
                    "style": "primary",
                    "action_id": f"status_done_{elapsed_minutes}",
                },
                _stop_button(),
            ],
        },
    ]

    return {"text": "Status update reminder", "blocks": blocks}


def build_confirmed_message(timestamp: str) -> dict:
    return {
        "text": f"Confirmed at {timestamp}",
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": f":white_check_mark: *Confirmed at {timestamp}*"}},
        ],
    }


def build_stop_summary(duration_minutes: int, escalations_triggered: int, status_updates_sent: int) -> dict:
    summary = (
        f":white_check_mark: *Incident stopped*\n\n"
        f"• Duration: {duration_minutes} minutes\n"
        f"• Escalation steps triggered: {escalations_triggered}\n"
        f"• Status updates sent: {status_updates_sent}"
    )

    return {
        "text": "Incident stopped",
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": summary}}],
    }
