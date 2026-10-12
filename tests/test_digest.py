from datetime import datetime, timezone
from pathlib import Path

import pytest

import digest

FIXTURE = str(Path(__file__).parent / "fixtures" / "sample_feed.xml")
NOW = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)


def test_clean_strips_html_entities_and_spaces():
    assert digest.clean("<p>Hello  <b>world</b>\n&amp; co</p><style>x{}</style>", 100) == "Hello world & co"


def test_clean_truncates():
    out = digest.clean("a" * 50, 10)
    assert len(out) == 10 and out.endswith("…")


def test_fetch_entries_filters_dedupes_and_keeps_undated():
    entries = digest.fetch_entries([FIXTURE], max_age_days=2, now=NOW)
    assert [e["link"] for e in entries] == [
        "https://example.com/recent",
        "https://example.com/nodate",
    ]
    assert entries[0]["title"] == "Recent & HTML"
    assert entries[0]["summary"] == "Hello world & co"
    assert entries[1]["date"] is None


def test_fetch_entries_wide_window_keeps_old():
    entries = digest.fetch_entries([FIXTURE], max_age_days=200, now=NOW)
    assert "https://example.com/old" in [e["link"] for e in entries]


def test_broken_feed_does_not_fail():
    assert digest.fetch_entries(["/nonexistent/path.xml"], 2, now=NOW) == []


@pytest.fixture(scope="module")
def model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("all-MiniLM-L6-v2")


def test_on_topic_scores_higher_than_cooking(model):
    entries = [
        {"title": "Neural networks predict rainfall from satellite data", "summary": ""},
        {"title": "A simple recipe for chocolate cake", "summary": ""},
    ]
    digest.score_entries(entries, ["Machine learning for weather forecasting."], model)
    assert entries[0]["score"] > entries[1]["score"] + 0.2


def test_select_filters_sorts_and_limits():
    entries = [{"score": s} for s in (0.1, 0.5, 0.3, 0.4)]
    assert [e["score"] for e in digest.select(entries, 0.2, 2)] == [0.5, 0.4]


def _config(tmp_path, **over):
    return {**digest.DEFAULTS, "output": str(tmp_path / "out" / "digest.xml"),
            "feed_url": "https://x.github.io/r/digest.xml", **over}


def _entry(n, score):
    return {"title": f"T{n}", "summary": f"S{n}", "link": f"https://e.com/{n}",
            "source": "Src", "date": None, "score": score}


def test_build_feed_order_and_valid_xml(tmp_path):
    import xml.etree.ElementTree as ET
    config = _config(tmp_path)
    entries = digest.select([_entry(1, 0.4), _entry(2, 0.9), _entry(3, 0.6)], 0.3, 3)
    digest.build_feed(entries, config, now=NOW)
    items = ET.parse(config["output"]).getroot().findall("./channel/item")
    assert [i.findtext("title") for i in items] == ["T2", "T3", "T1"]
    assert "score 0.90" in items[0].findtext("description")
    assert items[0].findtext("guid") == "https://e.com/2"


def test_build_feed_respects_top_k(tmp_path):
    import xml.etree.ElementTree as ET
    config = _config(tmp_path)
    entries = digest.select([_entry(n, 0.5 + n / 100) for n in range(10)], 0.3, 4)
    digest.build_feed(entries, config, now=NOW)
    assert len(ET.parse(config["output"]).getroot().findall("./channel/item")) == 4


def test_build_feed_empty_is_valid(tmp_path):
    import xml.etree.ElementTree as ET
    config = _config(tmp_path)
    digest.build_feed([], config, now=NOW)
    root = ET.parse(config["output"]).getroot()
    assert root.findtext("./channel/title") == "SonaRSS"
    assert root.findall("./channel/item") == []
