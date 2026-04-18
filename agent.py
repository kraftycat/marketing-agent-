"""Beauty / Skincare / Innovation RSS digest agent.

Fetches configured RSS feeds, filters articles in the lookback window that match
beauty/skincare/innovation keywords, summarizes them with Claude, and posts the
digest to Slack.
"""

from __future__ import annotations

import html
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import feedparser
import requests
import yaml
from anthropic import Anthropic
from bs4 import BeautifulSoup
from dotenv import load_dotenv

ROOT = Path(__file__).parent
FEEDS_FILE = ROOT / "feeds.yaml"


@dataclass
class Article:
    publication: str
    title: str
    link: str
    published: datetime
    summary: str


def load_config() -> tuple[list[dict], list[str]]:
    with FEEDS_FILE.open() as f:
        data = yaml.safe_load(f)
    feeds = data.get("feeds") or []
    keywords = [k.lower() for k in (data.get("keywords") or [])]
    if not feeds:
        sys.exit("No feeds configured in feeds.yaml")
    return feeds, keywords


def strip_html(value: str) -> str:
    if not value:
        return ""
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    return html.unescape(text)


def parse_date(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        struct = entry.get(key)
        if struct:
            return datetime(*struct[:6], tzinfo=timezone.utc)
    return None


def entry_matches(entry, keywords: list[str]) -> bool:
    if not keywords:
        return True
    haystack_parts = [
        entry.get("title", ""),
        entry.get("summary", ""),
        " ".join(t.get("term", "") for t in entry.get("tags", []) or []),
    ]
    haystack = " ".join(haystack_parts).lower()
    return any(k in haystack for k in keywords)


def fetch_articles(
    feeds: list[dict], keywords: list[str], since: datetime
) -> list[Article]:
    articles: list[Article] = []
    for feed in feeds:
        name = feed.get("name") or feed.get("url", "unknown")
        url = feed.get("url")
        if not url:
            continue
        parsed = feedparser.parse(url)
        if parsed.bozo and not parsed.entries:
            print(f"[fetch] {name}: FAILED — {parsed.bozo_exception}", file=sys.stderr)
            continue
        total = len(parsed.entries)
        kept = 0
        for entry in parsed.entries:
            published = parse_date(entry)
            if published is None or published < since:
                continue
            if not entry_matches(entry, keywords):
                continue
            kept += 1
            articles.append(
                Article(
                    publication=name,
                    title=strip_html(entry.get("title", "(untitled)")),
                    link=entry.get("link", ""),
                    published=published,
                    summary=strip_html(entry.get("summary", ""))[:1500],
                )
            )
        print(f"[fetch] {name}: {kept}/{total} entries kept", file=sys.stderr)
    articles.sort(key=lambda a: a.published, reverse=True)
    return articles


THEME_EMOJI = {
    "m&a": "💼",
    "mergers & acquisitions": "💼",
    "launches": "🚀",
    "product launches": "🚀",
    "ingredients & skincare": "🧴",
    "ingredients": "🧴",
    "skincare": "🧴",
    "trends & beauty culture": "✨",
    "trends": "✨",
    "retail & distribution": "🛍️",
    "retail & commerce": "🛍️",
    "retail": "🛍️",
    "tech & innovation": "🤖",
    "innovation": "🤖",
    "business & funding": "💰",
    "business": "💰",
    "funding": "💰",
}


def emoji_for(label: str) -> str:
    return THEME_EMOJI.get(label.strip().lower(), "•")


def slack_link(url: str, text: str) -> str:
    safe = text.replace("|", "/").replace(">", "").replace("<", "")
    return f"<{url}|{safe}>"


def render_digest(data: dict) -> str:
    lines: list[str] = []
    title = data.get("title") or "Beauty Industry Digest"
    lines.append(f"*{title}*")
    lines.append("")
    for theme in data.get("themes", []) or []:
        label = (theme.get("label") or "").strip()
        if not label:
            continue
        emoji = theme.get("emoji") or emoji_for(label)
        lines.append(f"{emoji} *{label}*")
        for item in theme.get("items", []) or []:
            headline = (item.get("headline") or "").strip()
            url = (item.get("url") or "").strip()
            insight = (item.get("insight") or "").strip()
            if not headline:
                continue
            link = slack_link(url, headline) if url else headline
            suffix = f" — {insight}" if insight else ""
            lines.append(f"• {link}{suffix}")
        lines.append("")
    takeaways = data.get("takeaways") or []
    if takeaways:
        lines.append("💡 *What it means*")
        for t in takeaways:
            t = (t or "").strip()
            if t:
                lines.append(f"• {t}")
    return "\n".join(lines).rstrip()


def summarize(
    client: Anthropic, model: str, articles: list[Article], window: str
) -> str:
    payload = [
        {
            "publication": a.publication,
            "title": a.title,
            "link": a.link,
            "published": a.published.isoformat(),
            "excerpt": a.summary,
        }
        for a in articles
    ]
    system = (
        "You are a beauty-industry analyst building a daily digest for a "
        "marketer tracking beauty, skincare, and innovation.\n\n"
        "Return ONLY a JSON object (no prose, no code fences) matching this "
        "schema:\n"
        "{\n"
        '  "title": "Beauty Industry Digest — <month day range>",\n'
        '  "themes": [\n'
        "    {\n"
        '      "label": "<one of: M&A | Launches | Ingredients & Skincare | '
        "Trends & Beauty Culture | Retail & Distribution | Tech & Innovation "
        '| Business & Funding>",\n'
        '      "items": [\n'
        '        {"headline": "<short rewritten headline>", '
        '"url": "<source url>", '
        '"insight": "<one crisp sentence of analyst insight>"}\n'
        "      ]\n"
        "    }\n"
        "  ],\n"
        '  "takeaways": ["<2-3 short marketer takeaways>"]\n'
        "}\n\n"
        "Only include themes that have at least one item. Keep insights "
        "concrete and specific. Do not wrap the JSON in markdown."
    )
    user = (
        f"Date range analyzed: {window}\n"
        f"Article count: {len(articles)}\n\n"
        "Articles (JSON):\n"
        f"{json.dumps(payload, indent=2)}"
    )
    resp = client.messages.create(
        model=model,
        max_tokens=2000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    raw = "".join(block.text for block in resp.content if block.type == "text")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            return raw
        data = json.loads(raw[start : end + 1])
    return render_digest(data)


def post_to_slack(webhook: str, window: str, count: int, digest: str) -> None:
    header = f":lipstick: *Beauty / Skincare / Innovation digest*\n_{window}_ • {count} article(s)"
    body = f"{header}\n\n{digest}"
    resp = requests.post(webhook, json={"text": body}, timeout=30)
    if resp.status_code >= 300:
        raise RuntimeError(f"Slack webhook error {resp.status_code}: {resp.text}")


def format_window(since: datetime, until: datetime) -> str:
    fmt = "%Y-%m-%d %H:%M UTC"
    return f"{since.strftime(fmt)} → {until.strftime(fmt)}"


def main() -> int:
    load_dotenv()
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    slack_webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not anthropic_key:
        sys.exit("ANTHROPIC_API_KEY is not set. See .env.example")
    if not slack_webhook:
        sys.exit("SLACK_WEBHOOK_URL is not set. See .env.example")

    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    lookback_hours = int(os.environ.get("LOOKBACK_HOURS", "24"))

    until = datetime.now(timezone.utc)
    since = until - timedelta(hours=lookback_hours)
    window = format_window(since, until)

    feeds, keywords = load_config()
    articles = fetch_articles(feeds, keywords, since)

    if not articles:
        post_to_slack(
            slack_webhook,
            window,
            0,
            "_No matching articles in this window._",
        )
        print("No articles; empty digest posted.")
        return 0

    client = Anthropic(api_key=anthropic_key)
    digest = summarize(client, model, articles, window)
    post_to_slack(slack_webhook, window, len(articles), digest)
    print(f"Posted digest with {len(articles)} articles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
