"""SonaRSS: reads RSS feeds, ranks entries by semantic similarity to reference
sentences, and keeps the best ones."""

import argparse
import html
import logging
import re
from calendar import timegm
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import yaml
from feedgen.feed import FeedGenerator

log = logging.getLogger("sonarss")

DEFAULTS = {
    "feed_url": "",
    "site_url": "",
    "feed_title": "SonaRSS",
    "language": "en",
    "output": "docs/digest.xml",
    "top_k": 15,
    "min_score": 0.30,
    "max_age_days": 3,
    "model": "all-MiniLM-L6-v2",
}


def load_config(path="config.yaml"):
    with open(path, encoding="utf-8") as f:
        config = {**DEFAULTS, **(yaml.safe_load(f) or {})}
    for key in ("feeds", "references"):
        if not config.get(key):
            raise ValueError(f"`{key}` is required in {path}")
    return config


def clean(text, max_len):
    """Strip HTML (tags and entities), normalize whitespace, truncate."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def entry_date(entry):
    """Entry date in UTC, or None if missing or unparsable."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        return datetime.fromtimestamp(timegm(parsed), tz=timezone.utc)
    except (OverflowError, ValueError, OSError):
        return None


def fetch_entries(feeds, max_age_days, now=None):
    """Recent, deduplicated entries from all feeds.

    A broken feed is skipped with a warning: it must never fail the run.
    An entry without a date is treated as recent.
    """
    now = now or datetime.now(timezone.utc)
    oldest = now - timedelta(days=max_age_days)
    entries, seen = [], set()
    for n, url in enumerate(feeds, 1):
        parsed = feedparser.parse(url)
        if parsed.bozo and not parsed.entries:
            log.warning("feed #%d unreadable, skipped", n)
            log.debug("  url: %s", url)
            continue
        source = clean(parsed.feed.get("title"), 80) or url
        kept = 0
        for e in parsed.entries:
            link = e.get("link")
            if not link or link in seen:
                continue
            date = entry_date(e)
            if date and date < oldest:
                continue
            seen.add(link)
            kept += 1
            entries.append({
                "title": clean(e.get("title"), 200),
                "summary": clean(e.get("summary") or e.get("description"), 600),
                "link": link,
                "source": source,
                "date": date,
            })
        log.debug("%3d recent entries: %s", kept, source)
    return entries


def score_entries(entries, references, model):
    """Add `score` to each entry: its max cosine similarity with any reference.

    Embeddings are normalized, so the dot product is the cosine similarity.
    """
    if not entries:
        return entries
    refs = model.encode(references, normalize_embeddings=True)
    texts = [f"{e['title']}. {e['summary']}" for e in entries]
    vecs = model.encode(texts, normalize_embeddings=True, batch_size=32)
    scores = (vecs @ refs.T).max(axis=1)
    for e, s in zip(entries, scores):
        e["score"] = float(s)
    return entries


def select(entries, min_score, top_k):
    kept = [e for e in entries if e["score"] >= min_score]
    return sorted(kept, key=lambda e: e["score"], reverse=True)[:top_k]


def build_feed(entries, config, now=None):
    """Write the RSS feed to `config["output"]`. Also works with 0 entries.

    feedgen's `add_entry()` inserts at the top, so entries are added in reverse
    order to get the best score first.
    """
    now = now or datetime.now(timezone.utc)
    site_url = config["site_url"] or config["feed_url"] or "https://example.com"
    fg = FeedGenerator()
    fg.title(config["feed_title"])
    fg.description(config["feed_title"])
    fg.language(config["language"])
    if config["feed_url"]:
        fg.link(href=config["feed_url"], rel="self")
    fg.link(href=site_url, rel="alternate")
    fg.lastBuildDate(now)

    for e in reversed(entries):
        fe = fg.add_entry()
        fe.id(e["link"])  # readers deduplicate on this identifier
        fe.guid(e["link"], permalink=True)
        fe.title(e["title"] or e["link"])
        fe.link(href=e["link"])
        # Readers render the description as HTML: a plain "\n" would be ignored,
        # so use tags. feedgen escapes the string, as RSS expects.
        header = html.escape(f"{e['source']} · score {e['score']:.2f}")
        fe.description(f"<p>{header}</p><p>{html.escape(e['summary'])}</p>")
        fe.pubDate(e["date"] or now)

    path = Path(config["output"])
    path.parent.mkdir(parents=True, exist_ok=True)
    fg.rss_file(str(path), pretty=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", nargs="?", default="config.yaml")
    parser.add_argument("--quiet", action="store_true",
                        help="logs without titles or feed names (for CI on a public repo)")
    parser.add_argument("--max-age-days", type=float, help="override max_age_days from the config")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.quiet else logging.DEBUG, format="%(message)s")
    for noisy in ("httpx", "httpcore", "urllib3", "huggingface_hub", "filelock"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    config = load_config(args.config)
    if args.max_age_days is not None:
        config["max_age_days"] = args.max_age_days

    from sentence_transformers import SentenceTransformer  # slow import, hence late

    entries = fetch_entries(config["feeds"], config["max_age_days"])
    model = SentenceTransformer(config["model"])
    score_entries(entries, config["references"], model)

    ranked = sorted(entries, key=lambda e: e["score"], reverse=True)
    log.debug("\nTop 20 of %d entries (min_score = %s):", len(ranked), config["min_score"])
    for e in ranked[:20]:
        mark = "*" if e["score"] >= config["min_score"] else " "
        log.debug("%s %.3f  [%s] %s", mark, e["score"], e["source"][:25], e["title"][:90])
    log.info("%d entries read", len(ranked))

    selected = select(entries, config["min_score"], config["top_k"])
    build_feed(selected, config)
    log.info("\n%d entries published to %s", len(selected), config["output"])


if __name__ == "__main__":
    main()
