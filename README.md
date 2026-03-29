#  Incident Bot

Slack bot that assists L1 support during Critical incidents with timed escalation reminders and status update templates.

## What it does

When a support engineer runs `/incident-start`, the bot sends personal DMs on a timer:

**Escalation ladder:**
- T+0 — Responsible hero
- T+10 — Head of Engineering + SRE hero (if needed)
- T+20 — Head of SRE (if needed)
- T+30 — Chief Architect
- T+40 — CTO

**Status updates every 15 min** with copy-paste templates for client and internal ticket.

Each message has a **Done** button. If not pressed within 2 minutes, the reminder repeats (max 3 times).

`/incident-stop` cancels all timers and sends a summary.

## Setup

### 1. Create Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → Create New App → From scratch
2. Name: `Incident Bot`, select your workspace

### 2. Configure the app

**OAuth & Permissions** → Bot Token Scopes:
- `chat:write`
- `commands`
- `im:write`

**Slash Commands** → Create:
- `/incident-start` — Description: "Start critical incident timer"
- `/incident-stop` — Description: "Stop active incident"

**Socket Mode** → Enable it

**App-Level Tokens** → Generate one with scope `connections:write`

**Install to Workspace** → Click Allow

### 3. Get your tokens

- **Bot Token** (`xoxb-...`): OAuth & Permissions → Bot User OAuth Token
- **App Token** (`xapp-...`): Basic Information → App-Level Tokens

### 4. Deploy to Railway

1. Push this project to a GitHub repository
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Add environment variables:
   - `SLACK_BOT_TOKEN` = your xoxb- token
   - `SLACK_APP_TOKEN` = your xapp- token
4. Railway auto-deploys. Done!

## Project structure

```
incident-bot/
  app.py              # Main app: commands, buttons, timers
  escalation.py       # Escalation config (edit timings here)
  messages.py         # Slack message builders
  requirements.txt    # Python dependencies
  Procfile            # Railway process config
  .env.example        # Environment variables template
```

## Customization

Edit `escalation.py` to change:
- Escalation steps and timings
- Status update interval (default: 15 min)
- Repeat delay (default: 2 min)
- Max repeats (default: 3)
- Client and internal templates
