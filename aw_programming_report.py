"""
ActivityWatch Programming Report
=================================
Reads an AW window-watcher JSON export and an AFK JSON export,
filters out idle time, categorizes events by regex rules,
and writes a Markdown report with:

  1. Daily totals for the overall "Programming" category
  2. Daily breakdown per sub-category
  3. Overall averages (category + hourly distribution)

Edit WINDOW_FILE, AFK_FILE, START_DATE and OUTPUT_FILE at the bottom.
"""

import json
import re
from collections import defaultdict
from datetime import datetime, timezone, date, timedelta

# ── Category rules ────────────────────────────────────────────────────────────

RULES = {
    "Stack Overflow":   r"Stack Overflow",
    "ActivityWatch":    r"ActivityWatch|aw-qt",
    "Visual Studio Code": r"Visual Studio Code|SmartCity-Frontend|Code\.exe",
    "IntelliJ":         r"IntelliJ|idea64\.exe|SmartCity-Backend|\.java|\.class|\.xml",
    "Git":              r"github|KDiff|MINGW64|Rebase|Resolve Merge conflicts|Commit"
                        r"|Git Extensions|zaricu22/SmartCity|SmartCity - Solo"
                        r"|SmartCity - Release|zaricu22/ForwardingAgent"
                        r"|zaricu22/Pharmacy|zaricu22/ZubarskaOrdinacija",
    "Render":           r"Render",
    "Text Editor":      r"Notepad|Sublime",
    "AI - Prog":        r"AI Prog",
    "File Explorer":    r"File Explorer|explorer\.exe|Windows|Task Manager",
    "DB":               r"DBeaver|MySQL Workbench",
}

PRIORITY_ORDER = [
    "ActivityWatch",
    "AI - Prog",
    "DB",
    "File Explorer",
    "Git",
    "IntelliJ",
    "Render",
    "Stack Overflow",
    "Text Editor",
    "Visual Studio Code",
]

# Pre-compile regex patterns once, from above RULES = { "cat": r"regex_pattern" }
PRECOMPILED_REGEX_PATTERNS = {cat: re.compile(regex_pattern, re.IGNORECASE) for cat, regex_pattern in RULES.items()}

# Standard hour-group boundaries shown in the report
HOUR_GROUPS = [8, 10, 12, 14, 16, 18, 20, 22]


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt(seconds: float) -> str:
    """Format seconds as  Xh YYm  (e.g. '2h 05m')."""
    h, m = divmod(int(seconds) // 60, 60)
    return f"{h}h {m:02d}m"


def hour_group_label(hour: int) -> str:
    """Return the two-hour slot label for a given hour (0-23)."""
    for boundary in reversed(HOUR_GROUPS):
        if hour >= boundary:
            return f"{boundary:02d}:00"
    return f"00:00"  # before first boundary


def classify(app: str, title: str) -> str | None:
    """
    Return the first matching category (by PRIORITY_ORDER) or None.
    Matches against both the app name and window title.
    """
    text = f"{app} {title}"
    for cat in PRIORITY_ORDER:
        if PRECOMPILED_REGEX_PATTERNS[cat].search(text):
            return cat
    return None


def load_afk_intervals(path: str) -> list[tuple[datetime, datetime]]:
    """
    Return a list of (start, end) UTC datetime pairs where the user was NOT afk.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    intervals: list[tuple[datetime, datetime]] = []
    for bucket in data["buckets"].values():
        for ev in bucket["events"]:
            if ev["data"].get("status") == "not-afk":
                # shift from json file utc timezone to local timezone to be related to hour_groups
                local_tz = datetime.now().astimezone().tzinfo
                start = datetime.fromisoformat(ev["timestamp"]).astimezone(local_tz)
                end_ts = start.timestamp() + ev["duration"]
                # shift from json file utc timezone to local timezone to be related to hour_groups
                end = datetime.fromtimestamp(end_ts, tz=local_tz)
                intervals.append((start, end))

    # Sort for fast lookup
    intervals.sort(key=lambda x: x[0])
    return intervals

# Return 'total_afk_active_secs' in one 'event_interval'
def active_overlap_deprecated(ev_start: datetime, ev_end: datetime,
                   afk_intervals: list[tuple[datetime, datetime]]) -> float:
    """
    Return the seconds of ev_start..ev_end that overlap with any not-afk interval.
    Uses a simple linear scan (fast enough for tens-of-thousands of events).
    Python 'datetime' comparison raise error when the two objects have different timezone,
    it is not case for timestamp comparison.
    """
    ev_s = ev_start.timestamp()
    ev_e = ev_end.timestamp()
    total = 0.0
    for afk_s, afk_e in afk_intervals:
        a_s = afk_s.timestamp()
        a_e = afk_e.timestamp()

        # Cases:
        #    event:    |════════════════════════════|   - within
        #    afk:              |══════════|
        #    ---
        #    event:          |════════════════════════| - bounded-before
        #    afk:      |══════════|
        #    ---
        #    event:    |════════════════════════|       - bounded-after
        #    afk:                         |══════════| 
        #    ---
        #    event:                     |════════════|  - outside-before
        #    afk:       |══════════|
        #    ---
        #    event:    |════════════|                   - outside-after
        #    afk:                       |══════════|
        #    ---
        
        # afk intervals are sorted - skip all afk-intervals before event_interval (outside-before)
        if a_e >= ev_s:
            continue  
        # afk intervals are sorted - stop all afk-intervals after event_interval (outside-after)
        if a_s >= ev_e:
            break          

        # calculate only parts of event within afk interval 
        overlap = min(ev_e, a_e) - max(ev_s, a_s)
        total += overlap
    return total

# Return 'afk_active_secs' in one 'event_interval' grouped by 'hour_group' 
def active_overlap_by_hours(ev_start, ev_end, afk_intervals):
    """
    Returns {slot_label: active_seconds} for each hour slot
    the event spans, intersected with not-afk intervals.
    """
    ev_s = ev_start.timestamp()
    ev_e = ev_end.timestamp()
    result = defaultdict(float)
    day = ev_start.replace(hour=0, minute=0, second=0, microsecond=0)
    # pass only once through afk_intervals and compare to event_interval
    for afk_s, afk_e in afk_intervals:
        a_s = afk_s.timestamp()
        a_e = afk_e.timestamp()

        # 'afk intervals' are sorted - skip each 'afk-interval' before 'event_interval' (outside-before)
        if a_e <= ev_s:
            continue  
        # 'afk intervals' are sorted - stop each 'afk-interval' after event_interval' (outside-after)
        if a_s >= ev_e:
            break
        
        for i, hour in enumerate(HOUR_GROUPS):    
            # slot boundaries
            slot_s = (day + timedelta(hours=hour)).timestamp()
            slot_e = (day + timedelta(hours=HOUR_GROUPS[i + 1])).timestamp() \
                 if i + 1 < len(HOUR_GROUPS) \
                 else (day + timedelta(hours=24)).timestamp()

            # 'hour_slots' are sorted - skip each 'hour_slot' before 'event_interval' or 'afk-interval' (outside-before)
            if slot_e <= ev_s or slot_e <= a_s:
                continue  
            # 'hour_slots' are sorted - stop each 'hour_slot' after 'event_interval' or 'afk-interval' (outside-after)
            if slot_s >= ev_e or slot_s >= a_e:
                break

            # Cases:
            #    hour_slot:    |════════════════════════════|   
            #    afk:               |═════════════════|  
            #    event:                 |══════════|
        
            # calculate only parts of 'event_interval' within 'hour_slot' within afk_interval
            overlap = min(slot_e, a_e, ev_e) - max(slot_s, a_s, ev_s)
            
            # sync format with hour_group_label(hour: int)
            label = f"{hour:02d}:00"

            # because of six above outside-cases-gaurds we can omit 'if overlap > 0' (negative values)
            # and safely write directly to result
            result[label] += overlap
            result['whole-event'] += overlap
            
    return result


# ── Main processing ───────────────────────────────────────────────────────────

def process(window_path: str, afk_path: str, start_date: date, output_path: str) -> None:
    print("Loading files …")
    with open(window_path, encoding="utf-8") as f:
        window_data = json.load(f)

    afk_intervals = load_afk_intervals(afk_path)

    daily_totals:  dict[str, float]            = defaultdict(float)
    daily_cats:    dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    hourly_totals: dict[str, float]            = defaultdict(float)

    weekday_totals:  dict[str, float]      = defaultdict(float)
    weekday_count:  dict[str, float]      = defaultdict(float)
    last_weekday = ""
    # sort by weekday
    weekday_totals['Monday'] = 0
    weekday_totals['Tuesday'] = 0
    weekday_totals['Wednesday'] = 0
    weekday_totals['Thursday'] = 0
    weekday_totals['Friday'] = 0
    weekday_totals['Saturday'] = 0
    weekday_totals['Sunday'] = 0

    total_events = skipped_unmatched = skipped_idle = skipped_before = 0
    local_tz = datetime.now().astimezone().tzinfo
    
    for bucket in window_data["buckets"].values():
        for ev in bucket["events"]:
            total_events += 1

            app   = ev["data"].get("app", "")
            title = ev["data"].get("title", "")
            cat   = classify(app, title)

            if cat is None:
                skipped_unmatched += 1
                continue
            
            # shift from json file utc timezone to local timezone to be related to hour_groups
            event_start = datetime.fromisoformat(ev["timestamp"]).astimezone(local_tz)

            # Skip events before start_date
            if event_start.date() < start_date:
                skipped_before += 1
                continue

            # shift from json file utc timezone to local timezone to be related to hour_groups
            event_end = datetime.fromtimestamp(event_start.timestamp() + ev["duration"], tz=local_tz)

            active_hours_secs = active_overlap_by_hours(event_start, event_end, afk_intervals)
            if active_hours_secs['whole-event'] <= 0:
                skipped_idle += 1
                continue

            date_str   = event_start.strftime("%Y-%m-%d")

            daily_totals[date_str]    += active_hours_secs['whole-event']
            daily_cats[date_str][cat] += active_hours_secs['whole-event']
            for hour_label, active_secs in active_hours_secs.items():
                hourly_totals[hour_label] += active_secs
            day_of_week = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A")
            weekday_totals[day_of_week] += active_hours_secs['whole-event']
            # because json is sorted by date, if date is changed it also means that weekday is changed
            if day_of_week != last_weekday:
                last_weekday = day_of_week
                weekday_count[day_of_week] += 1

    # ── Build Markdown ────────────────────────────────────────────────────────

    all_categories = sorted(RULES.keys())
    sorted_days    = sorted(daily_totals.keys())
    n_days         = len(sorted_days)
    generated_at   = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines: list[str] = []
    w = lines.append  # shorthand

    w("# ActivityWatch — Programming Report")
    w("")
    w(f"**Generated:** {generated_at}  ")
    w(f"**Period:** {start_date.strftime('%Y-%m-%d')} → {sorted_days[-1] if sorted_days else '—'}  ")
    w(f"**Days with data:** {n_days}  ")
    w(f"**Events processed:** {total_events:,}  ")
    w(f"**Unmatched:** {skipped_unmatched:,} *(no regex rule matched — browser, Spotify, system processes, etc.)*  ")
    w(f"**Idle-only:** {skipped_idle:,} *(matched a category but you were AFK for the entire event)*  ")
    w(f"**Before start date:** {skipped_before:,} *(matched and active, but occurred before {start_date.strftime('%Y-%m-%d')})*")
    w("")
    w("---")
    w("")

    RED = '<span style="font-weight: bold; color: red;">'
    GREEN = '<span style="font-weight: bold; color: green;">'
    YELLOW = '<span style="font-weight: bold; color: gold;">'
    ORANGE = '<span style="font-weight: bold; color: orange;">'
    PURPLE = '<span style="font-weight: bold; color: purple;">'
    BLACK = '<span style="font-weight: bold; color: black;">'
    RESET_COLOR = '</span>'
    COLOR = ""
    # ── 1. Daily breakdown with totals ────────────────────────────────────────
    w("## 1. Daily Breakdown by Sub-category")
    w("")
    w("> Time spent in each sub-category per day. `—` = no activity, `<1m` = under one minute.")
    w("")

    header_cats = [c for c in all_categories if any(
        daily_cats[d].get(c, 0) > 0 for d in sorted_days
    )]

    w("| Date | Total | " + " | ".join(header_cats) + " |")
    w("|------|------:|" + "|".join("------:" for _ in header_cats) + "|")

    for day in sorted_days:
        cells = []
        for cat in header_cats:
            secs = daily_cats[day].get(cat, 0)
            cells.append(fmt(secs) if secs > 60 else ("—" if secs == 0 else "<1m"))
        if daily_totals[day] < 3600: COLOR = BLACK      # < 1h
        if daily_totals[day] >= 3600: COLOR = GREEN     # > 1-2h
        if daily_totals[day] >= 10800: COLOR = YELLOW   # > 3h
        if daily_totals[day] >= 14400: COLOR = ORANGE   # > 4h
        if daily_totals[day] >= 18000: COLOR = RED      # > 5h
        if daily_totals[day] >= 21600: COLOR = PURPLE   # > 6h
        w(f"| {COLOR}{day}{RESET_COLOR} | {COLOR}{fmt(daily_totals[day])}{RESET_COLOR} | " + " | ".join(cells) + " |")

    w("")
    w("---")
    w("")

    # ── 2. Overall averages ───────────────────────────────────────────────────
    w(f"## 2. Overall Averages *(over {n_days} day(s))*")
    w("")

    # whole week
    avg_total = sum(daily_totals.values()) / n_days if n_days else 0
    w(f"> **Average daily Programming time (whole week): {fmt(avg_total)}**")
    w("")

    # working days
    sum_total_work = 0
    for weekday in ['Monday','Tuesday','Wednesday','Thursday','Friday']:
        sum_total_work += weekday_totals[weekday] / weekday_count[weekday]
    avg_total_work = sum_total_work / 5
    w(f"> **Average daily Programming time (working days): {fmt(avg_total_work)}**")
    w("")

    # 2a. Sub-category averages
    w("### Sub-category Averages")
    w("")
    w("| Sub-category | Avg / day | % of total | Activity |")
    w("|--------------|----------:|-----------:|----------|")

    cat_avgs = {}
    for cat in all_categories:
        total_cat = sum(daily_cats[d].get(cat, 0) for d in sorted_days)
        cat_avgs[cat] = total_cat / n_days if n_days else 0

    grand = sum(cat_avgs.values())
    for cat in sorted(cat_avgs, key=lambda c: -cat_avgs[c]):
        avg = cat_avgs[cat]
        if avg < 1:
            continue
        pct = (avg / grand * 100) if grand else 0
        bar_len = round(pct / 10)*3 if round(pct / 10)>0 else 1
        bar     = "█" * bar_len
        if bar_len/3 < 1: COLOR = BLACK
        if bar_len/3 >= 1: COLOR = GREEN
        if bar_len/3 >= 2: COLOR = YELLOW
        if bar_len/3 >= 3: COLOR = ORANGE
        if bar_len/3 >= 5: COLOR = RED 
        if bar_len/3 >= 7: COLOR = PURPLE      
        w(f"| {COLOR}{cat}{RESET_COLOR} | {fmt(avg)} | {pct:.1f}% | {COLOR}{bar}{RESET_COLOR} |")

    w("")

    # 2b. Hourly distribution
    w("### Hourly Distribution")
    w("")
    w("> When you are most active (avg per day per 2-hour slot).")
    w("")
    w("| Time slot | Avg / day | Activity |")
    w("|-----------|----------:|----------|")

    all_slots  = [f"{h:02d}:00" for h in HOUR_GROUPS]
    max_hourly = max((hourly_totals.get(s, 0) for s in all_slots), default=1)
    bar_width  = 24

    for slot in all_slots:
        secs    = hourly_totals.get(slot, 0)
        avg     = secs / n_days if n_days else 0
        bar_len = int((secs / max_hourly) * bar_width) if max_hourly else 0
        bar     = "█" * bar_len
        if bar_len < 4: COLOR = BLACK
        if bar_len > 4: COLOR = GREEN
        if bar_len > 8: COLOR = YELLOW
        if bar_len > 12: COLOR = ORANGE
        if bar_len > 16: COLOR = RED 
        if bar_len > 20: COLOR = PURPLE  
        w(f"| {COLOR}{slot}{RESET_COLOR} | {fmt(avg)} | {COLOR}{bar}{RESET_COLOR} |")

    w("")
    
    # 2c. Weekday distribution
    w("### Weekday Distribution")
    w("")
    w("> When you are most active (avg per day).")
    w("")
    w("| Weekday | Avg / day | Activity |")
    w("|---------|----------:|----------|")

    # use same bar_len as hours_ditribution
    bar_width  = 24

    for weekday, active_secs in weekday_totals.items():
        avg     = active_secs / weekday_count[weekday] if weekday_count[weekday] else 0
        # percentage [average_hours of weekday] of [8h work-time]
        bar_len = int(((avg // 3600) / 8) * bar_width)
        bar     = "█" * bar_len
        if bar_len < 4: COLOR = BLACK
        if bar_len > 4: COLOR = GREEN
        if bar_len > 8: COLOR = YELLOW
        if bar_len > 12: COLOR = ORANGE
        if bar_len > 16: COLOR = RED 
        if bar_len > 20: COLOR = PURPLE  
        w(f"| {COLOR}{weekday}{RESET_COLOR} | {fmt(avg)} | {COLOR}{bar}{RESET_COLOR} |")

    w("")
    w("---")
    w("")
    w("*Generated by `aw_programming_report.py`*")

    # ── Write file ────────────────────────────────────────────────────────────
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Report written to: {output_path}")
    print(f"Days included    : {n_days}  ({sorted_days[0] if sorted_days else '—'} → {sorted_days[-1] if sorted_days else '—'})")
    print(f"Avg daily time   : {fmt(avg_total)}")


# ── Config ────────────────────────────────────────────────────────────────────

WINDOW_FILE = "aw-bucket-export_aw-watcher-window_DESKTOP-T6T3R8I.json"
AFK_FILE    = "aw-bucket-export_aw-watcher-afk_DESKTOP-T6T3R8I.json"
START_DATE  = date(2026, 6, 1)   # only days on or after this date are included
OUTPUT_FILE = "aw_programming_report.md"

if __name__ == "__main__":
    process(WINDOW_FILE, AFK_FILE, START_DATE, OUTPUT_FILE)
