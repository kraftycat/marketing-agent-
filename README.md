# Beauty / Skincare / Innovation RSS digest agent

Scans a list of beauty publications daily, filters articles for
beauty/skincare/innovation, summarizes them with Claude, and posts the digest
to Slack with the date range analyzed.

## Quick start (GitHub Actions — no terminal needed)

You'll do everything in your browser on github.com.

### 1. Add your secrets

In the repo on GitHub:

1. Click **Settings** (top nav of the repo)
2. Left sidebar → **Secrets and variables** → **Actions**
3. Click **New repository secret** and add each of these (one at a time):
   - Name: `ANTHROPIC_API_KEY` → Value: your key starting with `sk-ant-...`
   - Name: `SLACK_WEBHOOK_URL` → Value: your Slack webhook URL

### 2. Enable Actions (if needed)

1. Click the **Actions** tab at the top of the repo
2. If prompted, click **I understand my workflows, go ahead and enable them**

### 3. Test it manually

1. In the **Actions** tab, click **Daily Beauty Digest** in the left sidebar
2. Click **Run workflow** (right side) → **Run workflow**
3. Wait ~1 minute. A green checkmark = success
4. Check your Slack channel for the digest
5. If it failed (red X), click the run and expand the "Run digest" step — common
   issues are a typo'd secret or a broken feed URL

### 4. It runs automatically

The workflow is scheduled for **13:00 UTC daily**
(`.github/workflows/daily-digest.yml`). Change the `cron:` line to pick a
different time — use https://crontab.guru to build your schedule.

## Editing the publication list

Edit `feeds.yaml` directly on GitHub:
1. Click `feeds.yaml` in the file list
2. Click the pencil (Edit) icon
3. Add/remove entries, commit to the branch

## Local run (optional, for developers)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in keys
python agent.py
```
