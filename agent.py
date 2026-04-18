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
        print(f"[fetch] {name}", file=sys.stderr)
        parsed = feedparser.parse(url)
        if parsed.bozo and not parsed.entries:
            print(f"  ! failed: {parsed.bozo_exception}", file=sys.stderr)
            continue
        for entry in parsed.entries:
            published = parse_date(entry)
            if published is None or published < since:
                continue
            if not entry_matches(entry, keywords):
                continue
            articles.append(
                Article(
                    publication=name,
                    title=strip_html(entry.get("title", "(untitled)")),
                    link=entry.get("link", ""),
                    published=published,
                    summary=strip_html(entry.get("summary", ""))[:1500],
                )
            )
    articles.sort(key=lambda a: a.published, reverse=True)
    return articles


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
        "You are a beauty-industry analyst. Write a concise, skimmable digest "
        "of the provided articles for a marketer tracking beauty, skincare, "
        "and innovation. Group by theme (e.g. Ingredients, Launches, M&A, "
        "Retail, Tech). For each item, give one crisp sentence and include a "
        "Markdown link to the source. End with a short 'What it means' "
        "takeaway (2-3 bullets)."
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
    return "".join(block.text for block in resp.content if block.type == "text")


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
