"""
Slack Block Kit message builders.
Constructs the DM messages for escalation reminders and status updates.
"""

from escalation import CLIENT_TEMPLATE, INTERNAL_TEMPLATE


def build_escalation_message(ticket_key: str, step: dict, step_index: int) -> dict:
    """Build an escalation reminder message with a Done button."""

    title = f":rotating_light: {step['title']} — {ticket_key}"

    notify_lines = []
    if step["notify"]:
        notify_lines.append(f"*Notify: {step['notify']}*")
    if step["optional"]:
        notify_lines.append(f"_{step['optional']}_")

    notify_text = "\n".join(notify_lines) if notify_lines else "_No mandatory notification at this step_"

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": title},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": notify_text},
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Done ✅"},
                    "style": "primary",
                    "action_id": f"escalation_done_{step_index}",
                    "value": ticket_key,
                }
            ],
        },
    ]

    return {
        "text": f"{step['title']} — {ticket_key}",  # fallback for notifications
        "blocks": blocks,
    }


def build_status_update_message(ticket_key: str, elapsed_minutes: int) -> dict:
    """Build a status update reminder with both templates and a Done button."""

    header = f":memo: {elapsed_minutes} min elapsed — time for status update\n*{ticket_key}*"

    client_text = CLIENT_TEMPLATE.replace("{{text}}", "_<your text here>_")
    internal_text = INTERNAL_TEMPLATE.replace("{{text}}", "_<your text here>_")

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": header},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Client update:*"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```{client_text}```"},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Internal update:*"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```{internal_text}```"},
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Done ✅"},
                    "style": "primary",
                    "action_id": f"status_done_{elapsed_minutes}",
                    "value": ticket_key,
                }
            ],
        },
    ]

    return {
        "text": f"Status update reminder — {ticket_key}",
        "blocks": blocks,
    }


def build_confirmed_message(timestamp: str) -> dict:
    """Build a replacement message after the user clicks Done."""
    return {
        "text": f"✅ Confirmed at {timestamp}",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"✅ *Confirmed at {timestamp}*",
                },
            }
        ],
    }


def build_stop_summary(ticket_key: str, duration_minutes: int,
                       escalations_triggered: int, status_updates_sent: int) -> dict:
    """Build the summary message when /incident-stop is called."""

    summary = (
        f":white_check_mark: *Incident stopped — {ticket_key}*\n\n"
        f"• Duration: {duration_minutes} minutes\n"
        f"• Escalation steps triggered: {escalations_triggered}\n"
        f"• Status updates sent: {status_updates_sent}"
    )

    return {
        "text": f"Incident stopped — {ticket_key}",
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": summary},
            }
        ],
    }
