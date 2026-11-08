# markets-briefing

An automated AI agent that turns each weekday's financial news into a
**~3-minute spoken markets briefing**.

Every weekday morning it:

1. **Collects** the day's top business stories from the NYT Top Stories API plus
   the Financial Times and Economist RSS feeds (last ~24 hours).
2. **Sorts** them into market-relevant buckets: markets, economy & policy,
   companies & deals, tech & AI, energy & commodities.
3. **Summarizes** the combined material with Claude (Anthropic API) into a
   ~400-word, spoken-style briefing that connects the stories.
4. **Converts** the summary to an MP3 with text-to-speech.
5. **Runs by itself** through a macOS LaunchAgent, with weekday, once-per-day,
   locking, and retry-on-failure guards.

**Tech:** Python (standard-library core) · Anthropic Claude API · NYT Top Stories
API · RSS (`feedparser`) · macOS `say` + `ffmpeg` / gTTS · launchd · `unittest`

Built with Claude as a coding assistant, as an exercise in taking an AI project
from idea to a daily automated workflow.

## The core digest

Without any flags, the tool builds a markets digest from the **NYT Top Stories
API** alone: it pulls the current Business (and optionally Technology) top
stories, sorts them into buckets, and prints a briefing as plain text or Markdown.

> The project API key is provisioned for the **Top Stories API only** — Article
> Search, Most Popular, and Times Wire return `401 Invalid ApiKey for given
> resource`. The tool is built around that constraint.

## Requirements

- Python 3.11+ — the core digest is standard library only.
- An NYT API key with the **Top Stories API** enabled: https://developer.nytimes.com/
- For `--summary` / `--audio`: `ANTHROPIC_API_KEY`, plus `pip install -r requirements.txt`
  (`feedparser` for the FT/Economist RSS feeds; `gTTS` only as an `--audio` fallback).
- `--audio` also needs macOS `say` and an mp3 encoder (`ffmpeg` or `lame`), or `gTTS`.

## Setup

```sh
git clone https://github.com/YOUR-USERNAME/markets-briefing.git
cd markets-briefing
pip install -r requirements.txt   # only needed for --summary / --audio
cp .env.example .env              # then add your own keys to .env
```

For interactive use, export the keys in your shell (or `set -a; . ./.env; set +a`):

```sh
export NYT_API_KEY="your-key-here"
export ANTHROPIC_API_KEY="your-key-here"   # for --summary / --audio
```

## Usage

```sh
./briefing.py                                   # Business section, text, to stdout
./briefing.py --section business technology      # merge two sections (de-duplicated)
./briefing.py --max-age 24 --limit 5            # last 24h, 5 stories per bucket
./briefing.py --all                             # every story, no limits
./briefing.py --format markdown --output briefing.md
```

### Options

| Flag | Default | Description |
| --- | --- | --- |
| `-s`, `--section NAME...` | `business` | Top Stories section(s) to pull. |
| `-f`, `--format {text,markdown}` | `text` (`markdown` if `--output` ends in `.md`) | Output format. |
| `-o`, `--output FILE` | stdout | Write the briefing to a file. |
| `-n`, `--limit N` | `6` | Max stories per bucket; `0` = unlimited. |
| `--max-age HOURS` | none | Drop stories whose `published_date` is older than `HOURS`. |
| `--all` | — | Shorthand for `--limit 0` with no age filter. |
| `--summary` | — | Send the combined briefing to Claude (`claude-sonnet-5`) for a spoken-style markets summary, printed to the console. Needs `ANTHROPIC_API_KEY`. |
| `--audio` | — | Run `--summary`, then save the summary as speech to `audio/briefing_<date>.mp3` (macOS `say` + `ffmpeg`/`lame`, or `gTTS`). |
| `--api-key KEY` | `$NYT_API_KEY` | Override the environment variable. |

Exit code `2` means a configuration or API error (missing key, bad section,
rate limit, network failure); the message goes to stderr.

## Sources feeding `--summary` / `--audio`

The console/file briefing is always **NYT Top Stories only**. When `--summary`
(or `--audio`) runs, the text handed to Claude is enriched with two more feeds,
each filtered to roughly the last 24 hours and clearly labeled by source:

| Source | Feed |
| --- | --- |
| NYT | Top Stories API (the bucketed digest above) |
| FT | `https://www.ft.com/rss/home` |
| Economist | `https://www.economist.com/the-world-in-brief/rss.xml`, falling back to `https://www.economist.com/finance-and-economics/rss.xml` when the digest feed is bot-gated (HTTP 403) |

RSS problems are non-fatal: the source is reported to stderr and marked
unavailable, and the summary still runs on whatever material was collected.

## How stories are bucketed

`mb/categorize.py` defines an ordered list of sections. Each article lands in the
**first** section whose NYT `des_facet` set, `subsection`, or keyword pattern it
matches, so nothing is duplicated:

1. **Markets & Investing** — stocks, bonds, yields, IPOs, VC, crypto, Wall Street
2. **Economy & Policy** — inflation, the Fed, rates, tariffs, jobs, GDP
3. **Companies & Deals** — earnings, M&A, layoffs, funding rounds, bankruptcies
4. **Tech & AI** — AI, chips, data centers, cloud, autonomous vehicles
5. **Energy & Commodities** — oil, gas, metals, gold
6. **Other Business** — everything else

Tune the facet sets and keyword regexes in `SECTIONS` to taste.

## Project layout

```
briefing.py            CLI entry point (+ --summary / --audio)
mb/nyt.py              Top Stories client + article normalization
mb/categorize.py       facet/keyword bucketing
mb/render.py           text and Markdown renderers
mb/rss.py              FT + Economist RSS fetch, 24h filter, source rendering
.env.example           template for the two API keys
run-briefing.sh        launchd wrapper: weekday + once-per-day guards, logging
com.erikrodriguez.markets-briefing.plist   LaunchAgent template
tests/test_categorize.py
tests/test_rss.py
```

## Tests

```sh
python3 -m unittest discover -s tests
```

## Scheduling a daily run

### cron

```sh
# crontab -e  — 7:00am on weekdays, written to a dated file
0 7 * * 1-5  NYT_API_KEY=... /path/to/briefing.py --max-age 24 -o "$HOME/briefings/$(date +\%F).md"
```

### launchd (macOS) — run once per weekday, on login / wake

`run-briefing.sh` + `com.erikrodriguez.markets-briefing.plist` drive
`briefing.py --summary --audio` from a LaunchAgent instead of cron. launchd has
no "screen unlock" event, so the plist uses `RunAtLoad` (login) plus
`StartInterval` 1800 (every 30 min while awake; missed ticks coalesce into one
run shortly after wake). The wrapper makes every trigger past the first each day
a no-op:

- **weekday guard** — silent exit on Sat/Sun (`date +%u > 5`)
- **once-per-day** — exit if `logs/.last-run` already holds today's date
- **lock** — `logs/.run.lock` dir prevents overlap; self-clears after 120 min
- a failed run is *not* stamped, so it retries on the next trigger

API keys come from `.env` in the project root (git-ignored) since a LaunchAgent
does not inherit your shell environment. All output — the same as cron's — is
appended to `logs/briefing.log` with `=== START ===` / `=== EXIT n ===` markers;
`logs/launchd.err.log` only catches wrapper-spawn failures.

```sh
# one-time install
cp .env.example .env && chmod 600 .env   # then fill in your keys
cp com.erikrodriguez.markets-briefing.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.erikrodriguez.markets-briefing.plist

# check it
launchctl print gui/$(id -u)/com.erikrodriguez.markets-briefing | grep -E 'state|last exit code'
tail -n 40 logs/briefing.log            # newest run; look for "=== EXIT 0 ==="
cat logs/.last-run                      # date of the last successful run

# force a fresh run
rm -f logs/.last-run
launchctl kickstart -k gui/$(id -u)/com.erikrodriguez.markets-briefing

# uninstall
launchctl bootout gui/$(id -u)/com.erikrodriguez.markets-briefing
rm ~/Library/LaunchAgents/com.erikrodriguez.markets-briefing.plist
```

`run-briefing.sh` finds the project folder from its own location. The plist is a
template: replace `YOUR_USERNAME` with the path to your clone before installing, and
adjust the Homebrew `python3` path (`/opt/homebrew/bin/python3`) in
`run-briefing.sh` if yours differs.
