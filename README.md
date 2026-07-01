# ActivityWatch Programming Report

A single-file Python script that turns raw [ActivityWatch](https://activitywatch.net/) exports into a readable Markdown report of your programming time.

## What it does

Reads two ActivityWatch JSON exports (window watcher + AFK watcher), filters out idle time, classifies each window event into a sub-category (IntelliJ, VS Code, Git, DB, etc.) and writes a Markdown report with:

- **Daily breakdown** — total programming time per day, split by sub-category, color-coded by intensity
- **Sub-category averages** — which tools you spend the most time in, with a visual bar
- **Hourly distribution** — 2-hour time slots showing when you are most productive
- **Weekday distribution** — average time per day of the week

## Requirements

Python 3.10+ (uses `str | None` union syntax). No third-party dependencies — only the standard library.

## Setup

1. Open ActivityWatch in your browser → **Raw Data** → export the two buckets:
   - `aw-watcher-window_<your-hostname>` → save as a `.json` file
   - `aw-watcher-afk_<your-hostname>` → save as a `.json` file

2. Place the exported files next to the script (or adjust the paths below).

3. Edit the config block at the bottom of `aw_programming_report.py`:

```python
WINDOW_FILE = "aw-bucket-export_aw-watcher-window_YOUR-HOSTNAME.json"
AFK_FILE    = "aw-bucket-export_aw-watcher-afk_YOUR-HOSTNAME.json"
START_DATE  = date(2026, 6, 1)   # include only days on or after this date
OUTPUT_FILE = "aw_programming_report.md"
```

4. Run:

```bash
python aw_programming_report.py
```

The report is written to `OUTPUT_FILE`. Open it in any Markdown viewer (VS Code, Obsidian, GitHub, etc.) to see the color-coded tables.

## Customizing categories

Categories are defined by the `RULES` dict near the top of the script — each entry maps a label to a regex pattern matched against the window title and app name:

```python
RULES = {
    "IntelliJ": r"IntelliJ|idea64\.exe|SmartCity-Backend|\.java",
    "Git":       r"github|KDiff|MINGW64|zaricu22/SmartCity",
    ...
}
```

Add, remove, or adjust patterns to match your own workflow. `PRIORITY_ORDER` controls which category wins when multiple rules match the same window.

## Data-science concepts implemented

- **Behavioral data science / digital phenotyping** — the script's core purpose: inferring work behavior from passive digital-trace logs (`process()`).
- **Time-series / temporal interval analysis** — computing overlap between event, AFK, and hour-slot intervals with timezone-aware timestamps (`active_overlap_by_hours()`, `load_afk_intervals()`).
- **Exploratory data analysis (EDA) / descriptive statistics** — daily, per-category, hourly, and weekday aggregation and averages (`process()`).
- **Rule-based classification (symbolic, non-ML)** — regex pattern matching with priority tie-breaking (`RULES`, `PRECOMPILED_REGEX_PATTERNS`, `classify()`).
- **ETL / data wrangling** — parsing raw JSON buckets and filtering idle/unmatched/out-of-range events (`process()`).
- **Reporting / data visualization** — Markdown tables and Unicode bar charts with color-coded intensity thresholds (`process()`).
