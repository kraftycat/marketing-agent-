# Beauty / Skincare / Innovation RSS digest agent

A small Python agent that:

1. Reads a list of RSS feeds from `feeds.yaml`.
2. Keeps articles from the last `LOOKBACK_HOURS` hours that mention beauty,
   skincare, innovation, or related keywords.
3. Summarizes them with Claude, grouped by theme.
4. Posts the digest (with the date range analyzed) to a Slack channel via an
   incoming webhook.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit .env and fill in your keys
```

### `.env` values

- `ANTHROPIC_API_KEY` — from https://console.anthropic.com/settings/keys
- `SLACK_WEBHOOK_URL` — create an Incoming Webhook at
  https://api.slack.com/messaging/webhooks
- `LOOKBACK_HOURS` — defaults to `24`
- `ANTHROPIC_MODEL` — defaults to `claude-haiku-4-5-20251001`

### Feeds

Edit `feeds.yaml` to add or remove publications. Each entry needs a `name` and
a feed `url`. Prefer section-specific feeds (e.g. `/beauty/feed`) over the main
site feed for less noise.

## Run it

```bash
python agent.py
```

## Schedule it daily (cron, 9am local)

```
0 9 * * * cd /path/to/marketing-agent- && .venv/bin/python agent.py >> agent.log 2>&1
```
