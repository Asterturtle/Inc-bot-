"""
Slack Block Kit message builders v7.
- Persistent control panel (updates in place)
- Compact progress bar in escalation/status messages
- Detailed progress in /incident-status
- Color-coded escalation
"""

from escalation import CLIENT_TEMPLATE, INTERNAL_TEMPLATE, ESCALATION_STEPS, STATUS_UPDATE_INTERVAL


# ---------------------------------------------------------------------------
# Shared components
# ---------------------------------------------------------------------------

def _compact_progress(current_step_index: int) -> str:
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
# Control panel (persistent, updates in place)
# ---------------------------------------------------------------------------

def build_control_panel(elapsed_min: int, current_step: int,
                        is_paused: bool = False) -> dict:
    """The single persistent message with status + buttons."""

    if is_paused:
        status_line = f":double_vertical_bar: *PAUSED* — {elapsed_min} min elapsed"
    else:
        status_line = f":red_circle: *ACTIVE* — {elapsed_min} min elapsed"

    progress = _compact_progress(current_step)

    elements = []
    if is_paused:
        elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": ":arrow_forward: Resume"},
            "action_id": "resume_incident",
        })
    else:
        elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": ":double_vertical_bar: Pause"},
            "action_id": "pause_incident",
        })

    elements.append({
        "type": "button",
        "text": {"type": "plain_text", "text": ":clock3: +5 min"},
        "action_id": "extend_incident",
    })
    elements.append({
        "type": "button",
        "text": {"type": "plain_text", "text": ":bar_chart: Status"},
        "action_id": "show_status",
    })
    elements.append({
        "type": "button",
        "text": {"type": "plain_text", "text": ":wastebasket: Clear"},
        "action_id": "clear_chat",
    })
    elements.append({
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
    })

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": status_line}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": progress}]},
        {"type": "actions", "elements": elements},
    ]

    return {"text": f"Incident control — {elapsed_min} min", "blocks": blocks}


# ---------------------------------------------------------------------------
# App Home
# ---------------------------------------------------------------------------

def build_app_home(has_active_incident: bool = False, duration_minutes: int = 0,
                   is_paused: bool = False, current_step: int = 0) -> list:
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":rotating_light: GR8Tech Incident Bot"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "Assists L1 support during Critical incidents with timed escalation reminders and status update templates."}},
        {"type": "divider"},
    ]

    if has_active_incident:
        status_emoji = ":double_vertical_bar:" if is_paused else ":red_circle:"
        status_text = "PAUSED" if is_paused else "ACTIVE"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"{status_emoji} *Incident {status_text}* — {duration_minutes} min elapsed"}})
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": _compact_progress(current_step)}]})
    else:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": ":large_green_circle: *No active incident*"}})
        blocks.append({
            "type": "actions",
            "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Start incident"}, "style": "primary", "action_id": "start_incident"}],
        })

    blocks.append({"type": "divider"})

    # --- Guide section ---
    blocks.append({"type": "header", "text": {"type": "plain_text", "text": ":book: How to use"}})

    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": (
        "*Getting started*\n"
        "Press the *Start incident* button above or type `/incident-start` in any channel. "
        "The bot will send you DMs with escalation reminders on a timer."
    )}})

    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": (
        "*Escalation ladder*\n"
        ":rotating_light: `T+0`  — Responsible hero\n"
        ":warning: `T+10` — Head of Engineering + _SRE hero (if needed)_\n"
        ":large_orange_circle: `T+20` — _Head of SRE (if needed)_\n"
        ":red_circle: `T+30` — Chief Architect\n"
        ":fire: `T+40` — CTO"
    )}})

    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": (
        "*Status updates*\n"
        "Every 15 minutes you get a reminder with copy-paste templates for the client ticket and internal ticket."
    )}})

    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": (
        "*Control panel buttons*\n"
        ":double_vertical_bar: *Pause / Resume* — Freeze all timers (e.g. waiting for vendor fix)\n"
        ":clock3: *+5 min* — Push next escalation by 5 minutes\n"
        ":bar_chart: *Status* — Detailed progress view with all steps\n"
        ":wastebasket: *Clear* — Delete all bot messages, keep the panel\n"
        "*Stop* — End the incident, clean up, show summary"
    )}})

    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": (
        "*Done button*\n"
        "Each escalation and status update has a *Done* button. Press it to confirm the action. "
        "If you don't press it within 2 minutes, the reminder will repeat (max 3 times)."
    )}})

    blocks.append({"type": "divider"})

    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": (
        "*Commands*\n"
        "`/incident-start` — Start the incident timer\n"
        "`/incident-stop` — Stop and show summary\n"
        "`/incident-status` — Detailed progress view"
    )}})

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

    next_text = _next_step_text(step_index)

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": title}},
        {"type": "section", "text": {"type": "mrkdwn", "text": notify_text}},
        {"type": "divider"},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": next_text}]},
        {
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "Done"},
                "style": "primary",
                "action_id": f"escalation_done_{step_index}",
                "value": f"T+{step['minutes']} — {step['notify'] or step['optional']}",
            }],
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
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "Done"},
                "style": "primary",
                "action_id": f"status_done_{elapsed_minutes}",
                "value": f"Status update ({elapsed_minutes} min)",
            }],
        },
    ]

    return {"text": "Status update reminder", "blocks": blocks}


# ---------------------------------------------------------------------------
# Status view (detailed, for /incident-status and Status button)
# ---------------------------------------------------------------------------

def build_status_view(elapsed_min: int, current_step: int,
                      escalations_triggered: int, status_updates_sent: int,
                      is_paused: bool = False) -> dict:
    status_emoji = ":double_vertical_bar: PAUSED" if is_paused else ":red_circle: ACTIVE"
    header = f"*{status_emoji} — {elapsed_min} min elapsed*"
    progress = _detailed_progress(current_step)
    stats = (
        f"• Escalation steps triggered: {escalations_triggered}\n"
        f"• Status updates sent: {status_updates_sent}"
    )

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": progress}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": stats}},
    ]

    return {"text": f"Incident status — {elapsed_min} min", "blocks": blocks}


# ---------------------------------------------------------------------------
# Utility messages
# ---------------------------------------------------------------------------

def build_confirmed_message(timestamp: str, description: str = "") -> dict:
    if description:
        text = f":white_check_mark: *{description}* — confirmed at {timestamp}"
    else:
        text = f":white_check_mark: *Confirmed at {timestamp}*"
    return {
        "text": text,
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
    }


def build_stop_summary(duration_minutes: int, escalations_triggered: int, status_updates_sent: int) -> dict:
    summary = (
        f":white_check_mark: *Incident stopped*\n\n"
        f"• Duration: {duration_minutes} minutes\n"
        f"• Escalation steps triggered: {escalations_triggered}\n"
        f"• Status updates sent: {status_updates_sent}"
    )
    return {"text": "Incident stopped", "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": summary}}]}


def build_welcome_message() -> dict:
    """Pinned welcome message with Start button in the Messages tab."""
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": ":rotating_light: *GR8Tech Incident Bot*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "Press the button below to start a Critical incident timer. You'll receive escalation reminders and status update templates right here."}},
        {
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": ":rotating_light: Start Incident"},
                "style": "primary",
                "action_id": "start_incident",
            }],
        },
    ]
    return {"text": "GR8Tech Incident Bot — Start Incident", "blocks": blocks}
