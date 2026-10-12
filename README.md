# SonaRSS

A personal RSS digest, generated every morning with no manual work. It reads a list of feeds, ranks recent articles by **semantic similarity** to a few sentences describing your interests, and publishes the best ones as an RSS feed served by GitHub Pages.

Fully open source and free: no API key, no server, no LLM. Ranking uses a small embedding model (`all-MiniLM-L6-v2`) running on CPU in GitHub Actions.

## How it works

1. Reads the feeds in `config.yaml` (a broken feed is skipped, never fails the run).
2. Keeps recent entries (`max_age_days`), without duplicate links.
3. Scores each entry (title + summary) by its max cosine similarity to any of the `references`.
4. Entries above `min_score` are sorted, the best `top_k` are written to `docs/digest.xml`.
5. The workflow commits that file and GitHub Pages serves it.

## Setup (fork)

1. Fork this repo. It must be **public** (Pages is free only for public repos). The feed only contains titles, links and excerpts of public articles.
2. Copy `config.example.yaml` to `config.yaml` (git-ignored) and set `feed_url` to `https://YOUR_USER.github.io/YOUR_REPO/digest.xml`, plus `site_url`, `feeds` and `references`. Then paste its content into a repository secret named `CONFIG_YAML` (*Settings → Secrets and variables → Actions*), see "Keeping your config private".
3. *Settings → Actions → General → Workflow permissions*: **Read and write permissions**.
4. *Settings → Pages*: **Deploy from a branch**, `main`, `/docs`.
5. *Actions → Digest → Run workflow*. A minute or two later the feed URL responds.
6. Subscribe to that URL in your reader (NetNewsWire: *File → New Web Feed…*, not *Import Subscriptions*, which expects OPML).

## Keeping your config private

The repo is public, but your `references` and `feeds` don't have to be. `config.yaml` is git-ignored; the workflow writes the `CONFIG_YAML` secret to `config.yaml` at run time (without the secret, it falls back to `config.example.yaml`) and runs with `--quiet`, so public logs contain no titles or feed names. The published `digest.xml` still shows the selected articles.

Updating a secret does not trigger a run: launch *Actions → Digest → Run workflow* to apply it right away, otherwise it takes effect at the next scheduled run.

## Configuration (`config.yaml`)

Only `feeds` and `references` are required.

| Field | Default | Meaning |
|---|---|---|
| `references` | – | English sentences describing what you care about. Edit freely over time. |
| `feeds` | – | RSS/Atom URLs to read. |
| `min_score` | 0.30 | Similarity threshold (0–1). Higher = stricter. |
| `top_k` | 15 | Maximum entries published. |
| `max_age_days` | 3 | Only keep entries from the last N days. Keep it consistent with the schedule. |

To calibrate `min_score`, each entry shows its score ("Source · score 0.64") and each run logs the top 20.

## Change the schedule

Edit the single `cron:` line in [.github/workflows/digest.yml](.github/workflows/digest.yml) (UTC). Examples are in the file: daily (default, `0 5 * * *`), weekdays (`0 5 * * 1-5`), weekly (`0 5 * * 5`). Then adjust `max_age_days` (about 3 daily, 8 weekly). An article may show up in several consecutive digests; readers dedupe on the link.

## Run on demand

- **GitHub**: *Actions → Digest → Run workflow*, with an optional `max_age_days` override (e.g. 14 to catch up).
- **Local**: see below.

## Local use

Python 3.12 recommended.

```bash
python -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU torch first (avoids CUDA on Linux)
pip install -r requirements.txt

python -m pytest                      # offline tests (model downloaded on first run)
python digest.py                      # real run, writes docs/digest.xml
python digest.py --max-age-days 14    # wider window
python digest.py --quiet              # no titles/feed names in logs (as in CI)
python digest.py other_config.yaml    # another config file
```

To preview in a reader: `python -m http.server 8000 -d docs`, then `http://localhost:8000/digest.xml`. The workflow commits to `main`, so `git pull` before pushing.

## Notes

- Summaries are truncated (600 chars) since the feed is public; use your reader's reader view for full articles.
- `digest.xml` changes on every run (build date), so the daily commit also keeps the scheduled workflow from being disabled after 60 days of inactivity.
- The model is English-only; consider a multilingual one for non-English sources.
