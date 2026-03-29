"""
Escalation ladder and status update configuration.
Edit this file to change timings, roles, or templates.
"""

ESCALATION_STEPS = [
    {
        "minutes": 0,
        "title": "Critical incident started",
        "notify": "Responsible hero",
        "optional": None,
        "short": "Hero",
        "emoji": ":rotating_light:",
    },
    {
        "minutes": 10,
        "title": "10 min elapsed",
        "notify": "Head of Engineering",
        "optional": "SRE hero (if needed)",
        "short": "HoE",
        "emoji": ":warning:",
    },
    {
        "minutes": 20,
        "title": "20 min elapsed",
        "notify": None,
        "optional": "Head of SRE (if needed)",
        "short": "HoSRE",
        "emoji": ":large_orange_circle:",
    },
    {
        "minutes": 30,
        "title": "30 min elapsed",
        "notify": "Chief Architect",
        "optional": None,
        "short": "Architect",
        "emoji": ":red_circle:",
    },
    {
        "minutes": 40,
        "title": "40 min elapsed",
        "notify": "CTO",
        "optional": None,
        "short": "CTO",
        "emoji": ":fire:",
    },
]

STATUS_UPDATE_INTERVAL = 15
MAX_REPEATS = 3
REPEAT_DELAY_SECONDS = 120

CLIENT_TEMPLATE = """Hello!

{{text}}

Best regards,
GR8Tech Support"""

INTERNAL_TEMPLATE = """Who? L1 Team
What was done? {{text}}"""
