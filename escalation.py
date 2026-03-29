"""
Escalation ladder and status update configuration.
Edit this file to change timings, roles, or templates.
"""

# Escalation steps: (minutes_after_start, message, is_optional)
ESCALATION_STEPS = [
    {
        "minutes": 0,
        "title": "Critical incident started",
        "notify": "Responsible hero",
        "optional": None,
    },
    {
        "minutes": 10,
        "title": "10 min elapsed",
        "notify": "Head of Engineering",
        "optional": "SRE hero (if needed)",
    },
    {
        "minutes": 20,
        "title": "20 min elapsed",
        "notify": None,
        "optional": "Head of SRE (if needed)",
    },
    {
        "minutes": 30,
        "title": "30 min elapsed",
        "notify": "Chief Architect",
        "optional": None,
    },
    {
        "minutes": 40,
        "title": "40 min elapsed",
        "notify": "CTO",
        "optional": None,
    },
]

# Status update interval in minutes
STATUS_UPDATE_INTERVAL = 15

# How many times to repeat a reminder if not confirmed
MAX_REPEATS = 3

# Seconds to wait before repeating unconfirmed reminder
REPEAT_DELAY_SECONDS = 120  # 2 minutes

# Client-facing template
CLIENT_TEMPLATE = """Hello!

{{text}}

Best regards,
GR8Tech Support"""

# Internal ticket template
INTERNAL_TEMPLATE = """Who? L1 Team
What was done? {{text}}"""
