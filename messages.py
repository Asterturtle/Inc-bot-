"""
Slack Block Kit message builders v6.
- Compact progress bar (variant A) in every message
- Detailed progress bar (variant B) in /incident-status
- Color-coded escalation levels
- Stop, Pause/Resume, Extend buttons
"""

from escalation import CLIENT_TEMPLATE, INTERNAL_TEMPLATE, ESCALATION_STEPS, STATUS_UPDATE_INTERVAL


# ---------------------------------------------------------------------------
# Shared components
# ---------------------------------------------------------------------------

def _stop_button():
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": "Stop"},
        "style": "danger",
        "action_id": "stop_incident",
        "confirm": {
            "title": {"type": "plain_text", "text": "Stop incident?"},
            "text": {"type": "mrkdwn", "text": "This will cancel all timers and end the incident."},
            "confirm": {"type": "plain_text", "text": "Yes, stop"},
            "deny": {"type": "plain_text", "text": "Cancel"},
        },
    }


def _pause_button(is_paused: bool = False):
    if is_paused:
        return {
            "type": "button",
            "text": {"type": "plain_text", "text": ":arrow_forward: Resume"},
            "action_id": "resume_incident",
        }
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": ":double_vertical_bar: Pause"},
        "action_id": "pause_incident",
    }


def _extend_button():
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": "+5 min"},
        "action_id": "extend_incident",
    }


def _compact_progress(current_step_index: int) -> str:
    """Variant A: one-line emoji progress bar."""
    parts = []
    for i, step in enumerate(ESCALATION_STEPS):
        name = step["short"]
        if i < current_step_index:
            parts.append(f":white_check_mark: {name}")
        elif i == current_step_index:
            parts.append(f":large_orange_circle: *{name}*")
        else:
            parts.append(f":white_circle: {name}")
    return " → ".join(parts)


def _detailed_progress(current_step_index: int) -> str:
    """Variant B: multi-line detailed progress for /incident-status."""
    lines = []
    for i, step in enumerate(ESCALATION_STEPS):
        who = step["notify"] or step["optional"] or "—"
        if i < current_step_index:
            lines.append(f":white_check_mark: T+{step['minutes']}  {who}")
        elif i == current_step_index:
            lines.append(f":large_orange_circle: *T+{step['minutes']}  {who}* ← current")
        else:
            lines.append(f":white_circle: T+{step['minutes']}  {who}")
    return "\n".join(lines)


def _next_step_text(current_step_index: int) -> str:
    """Next escalation + next status update info."""
    current_min = ESCALATION_STEPS[current_step_index]["minutes"]

    next_esc = None
    for s in ESCALATION_STEPS:
        if s["minutes"] > current_min:
            next_esc = s
            break

    next_status_min = STATUS_UPDATE_INTERVAL
    while next_status_min <= current_min:
        next_status_min += STATUS_UPDATE_INTERVAL

    parts = []
    if next_esc:
        mins_until = next_esc["minutes"] - current_min
        who = next_esc["notify"] or next_esc["optional"]
        parts.append(f":arrow_right: Next escalation: *{who}* — in {mins_until} min")
    parts.append(f":clipboard: Next status update in {next_status_min - current_min} min")
    return "\n".join(parts)


def _next_status_text(elapsed_minutes: int) -> str:
    """Next step info for status update messages."""
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


# ---------------------------------------------------------------------------
# App Home
# ---------------------------------------------------------------------------

def build_app_home(has_active_incident: bool = False, duration_minutes: int = 0,
                   is_paused: bool = False, current_step: int = 0) -> list:
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
        status_emoji = ":double_vertical_bar:" if is_paused else ":red_circle:"
        status_text = "PAUSED" if is_paused else "ACTIVE"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"{status_emoji} *Incident {status_text}* — {duration_minutes} min elapsed"},
        })
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": _compact_progress(current_step)}],
        })
        elements = [_pause_button(is_paused), _extend_button(), _stop_button()]
        blocks.append({"type": "actions", "elements": elements})
    else:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":large_green_circle: *No active incident*"},
        })
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "Start incident"},
                "style": "primary",
                "action_id": "start_incident",
            }],
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "Commands: `/incident-start`  `/incident-stop`  `/incident-status`"}],
    })
    return blocks


# ---------------------------------------------------------------------------
# Escalation message
# ---------------------------------------------------------------------------

def build_escalation_message(step: dict, step_index: int) -> dict:
    emoji = step["emoji"]
    title = f"{emoji} {step['title']}"

    notify_lines = []
    if step["notify"]:
        notify_lines.append(f"*Notify: {step['notify']}*")
    if step["optional"]:
        notify_lines.append(f"_{step['optional']}_")
    notify_text = "\n".join(notify_lines) if notify_lines else "_No mandatory notification at this step_"

    progress = _compact_progress(step_index)
    next_text = _next_step_text(step_index)

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": title}},
        {"type": "section", "text": {"type": "mrkdwn", "text": notify_text}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": progress}]},
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
                _pause_button(),
                _extend_button(),
                _stop_button(),
            ],
        },
    ]

    return {"text": step["title"], "blocks": blocks}


# ---------------------------------------------------------------------------
# Status update message
# ---------------------------------------------------------------------------

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
                _pause_button(),
                _stop_button(),
            ],
        },
    ]

    return {"text": "Status update reminder", "blocks": blocks}


# ---------------------------------------------------------------------------
# Status command (detailed view)
# ---------------------------------------------------------------------------

def build_status_view(elapsed_min: int, current_step: int,
                      escalations_triggered: int, status_updates_sent: int,
                      is_paused: bool = False) -> dict:
    status_emoji = ":double_vertical_bar: PAUSED" if is_paused else ":red_circle: ACTIVE"

    header = f"{status_emoji} — {elapsed_min} min elapsed"
    progress = _detailed_progress(current_step)
    stats = (
        f"• Escalation steps triggered: {escalations_triggered}\n"
        f"• Status updates sent: {status_updates_sent}"
    )

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{header}*"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": progress}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": stats}},
        {
            "type": "actions",
            "elements": [_pause_button(is_paused), _extend_button(), _stop_button()],
        },
    ]

    return {"text": f"Incident status — {elapsed_min} min", "blocks": blocks}


# ---------------------------------------------------------------------------
# Utility messages
# ---------------------------------------------------------------------------

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


def build_paused_message() -> dict:
    return {
        "text": "Incident paused",
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": ":double_vertical_bar: *Incident paused.* All timers are on hold. Press *Resume* to continue."}},
            {"type": "actions", "elements": [_pause_button(is_paused=True), _stop_button()]},
        ],
    }


def build_resumed_message() -> dict:
    return {
        "text": "Incident resumed",
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": ":arrow_forward: *Incident resumed.* Timers are running again."}},
        ],
    }


def build_extended_message(extra_minutes: int) -> dict:
    return {
        "text": f"Extended by {extra_minutes} min",
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": f":clock3: *Next escalation extended by {extra_minutes} minutes.*"}},
        ],
    }
