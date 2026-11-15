#!/usr/bin/env python3
"""Render README.md from scripts/profile.toml plus Codeberg and Lichess data, and the activity heatmap in assets/.

Stdlib only. Needs git on PATH. Usage: python3 scripts/stats.py
"""

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.request
from collections import Counter
from xml.sax.saxutils import escape

USER = "Spoljarevic"
LICHESS = "Spoljarevic"
FORGE = "https://codeberg.org"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")

try:
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo("Europe/Berlin")
except Exception:
    TZ = dt.UTC

# palette of the neural pulse lattice banner
BG = "#050810"
GRIDLINE = "#0e1a30"
EDGE = "#1a2a4a"
TEXT = "#a5b4cf"
CREAM = "#fef3c7"
BLUE = "#4fbcff"
VIOLET = "#a78bfa"
CYAN = "#7ddbff"
FONT = "'JetBrains Mono', 'IBM Plex Mono', ui-monospace, monospace"
HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(HERE, "profile.toml")
README = os.path.join(HERE, "..", "README.md")

# extension -> language; only what is worth showing on an infra profile
EXT = {
    ".yml": "YAML",
    ".yaml": "YAML",
    ".j2": "Jinja",
    ".jinja": "Jinja",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".py": "Python",
    ".nu": "Nushell",
    ".lua": "Lua",
    ".tf": "Terraform",
    ".hcl": "Terraform",
    ".container": "Quadlet",
    ".network": "Quadlet",
    ".volume": "Quadlet",
    ".pod": "Quadlet",
    ".kube": "Quadlet",
    ".build": "Quadlet",
    ".image": "Quadlet",
    ".html": "HTML",
    ".css": "CSS",
    ".js": "JavaScript",
    ".toml": "TOML",
    ".conf": "Config",
    ".ini": "Config",
    ".glsl": "GLSL",
    ".frag": "GLSL",
    ".vert": "GLSL",
}
FILENAMES = {"Dockerfile": "Dockerfile", "Containerfile": "Dockerfile"}
SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", "__pycache__"}
SKIP_REPOS = {"Personal-Site-Old", "Wallpapers"}


def get(url, tries=4, with_headers=False):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"{USER}-profile-stats", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return (json.load(r), r.headers) if with_headers else json.load(r)
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"retry {url}: {e}", file=sys.stderr)
            time.sleep(2 * (i + 1))


def repos():
    out, page = [], 1
    while True:
        batch = get(f"{FORGE}/api/v1/users/{USER}/repos?limit=50&page={page}")
        out += batch
        if len(batch) < 50:
            return [r for r in out if not r["fork"] and not r["mirror"] and not r.get("private")]
        page += 1


def heatmap():
    days = Counter()
    for e in get(f"{FORGE}/api/v1/users/{USER}/heatmap"):
        days[dt.datetime.fromtimestamp(e["timestamp"], TZ).date()] += e["contributions"]
    return days


def commits(name, today, weeks=12):
    """Total commit count, commits per week for the last `weeks` weeks (oldest first) and the last commit date."""
    base = f"{FORGE}/api/v1/repos/{USER}/{name}/commits?stat=false&verification=false&files=false"
    first, headers = get(f"{base}&limit=1", with_headers=True)
    since = today - dt.timedelta(weeks=weeks)
    per_week, page = [0] * weeks, 1
    while True:
        batch = get(f"{base}&limit=50&page={page}&since={since:%Y-%m-%d}T00:00:00Z")
        for c in batch:
            age = (today - dt.datetime.fromisoformat(c["created"]).astimezone(TZ).date()).days
            if 0 <= age < weeks * 7:
                per_week[weeks - 1 - age // 7] += 1
        if len(batch) < 50:
            break
        page += 1
    last = dt.datetime.fromisoformat(first[0]["created"]).astimezone(TZ).date() if first else None
    return int(headers.get("X-Total-Count") or len(first)), per_week, last


def count_lines(repo_list):
    lines, quadlets, tasks = Counter(), 0, 0
    with tempfile.TemporaryDirectory() as tmp:
        for r in repo_list:
            if r["name"] in SKIP_REPOS or r.get("empty"):
                continue
            dest = os.path.join(tmp, r["name"])
            res = subprocess.run(["git", "clone", "-q", "--depth", "1", r["clone_url"], dest], capture_output=True)
            if res.returncode:
                print(f"clone failed {r['name']}: {res.stderr.decode().strip()}", file=sys.stderr)
                continue
            for root, dirs, files in os.walk(dest):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                in_tasks = os.path.basename(root) in ("tasks", "handlers")
                for f in files:
                    if ".min." in f:
                        continue
                    ext = os.path.splitext(f)[1].lower()
                    lang = FILENAMES.get(f) or EXT.get(ext)
                    if ext in EXT and EXT[ext] == "Quadlet":
                        quadlets += 1
                    if not lang:
                        continue
                    try:
                        with open(os.path.join(root, f), encoding="utf-8", errors="replace") as fh:
                            text = fh.read()
                    except OSError:
                        continue
                    lines[lang] += sum(1 for ln in text.splitlines() if ln.strip())
                    # ansible tasks: named entries in task/handler files and playbooks
                    if lang == "YAML" and (in_tasks or "\n  hosts:" in text or text.startswith("- hosts:") or "\n- hosts:" in text):
                        tasks += sum(1 for ln in text.splitlines() if ln.lstrip().startswith("- name:"))
    return lines, quadlets, tasks


def streaks(days, today):
    longest = run = 0
    d = min(days) if days else today
    while d <= today:
        run = run + 1 if days.get(d) else 0
        longest = max(longest, run)
        d += dt.timedelta(days=1)
    current, d = 0, today if days.get(today) else today - dt.timedelta(days=1)
    while days.get(d):
        current += 1
        d -= dt.timedelta(days=1)
    return current, longest


def frame(w, h, title, subtitle=""):
    grid = "".join(f'<line x1="{x}" y1="0" x2="{x}" y2="{h}"/>' for x in range(80, w, 120))
    grid += "".join(f'<line x1="0" y1="{y}" x2="{w}" y2="{y}"/>' for y in range(60, h, 80))
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-labelledby="t">',
        f'  <title id="t">{escape(title)}</title>',
        f'  <rect width="{w}" height="{h}" fill="{BG}"/>',
        f'  <g stroke="{GRIDLINE}" stroke-width="0.5">{grid}</g>',
        f'  <rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" fill="none" stroke="{EDGE}" stroke-width="0.8"/>',
        f'  <g font-family="{FONT}" fill="{TEXT}">',
        f'    <text x="32" y="40" font-size="10" letter-spacing="4" fill="{BLUE}">{escape(title.upper())}</text>',
        f'    <text x="32" y="58" font-size="10" letter-spacing="4">{escape(subtitle.upper())}</text>' if subtitle else "",
    ]


def close(parts):
    return "\n".join(p for p in parts if p) + "\n  </g>\n</svg>\n"


def stat(x, y, value, label):
    return (
        f'    <text x="{x}" y="{y}" font-size="24" font-weight="700" fill="{CREAM}">{escape(str(value))}</text>\n'
        f'    <text x="{x}" y="{y + 20}" font-size="9" letter-spacing="3">{escape(label)}</text>'
    )


def rule(y, w):
    return f'    <line x1="32" y1="{y}" x2="{w - 32}" y2="{y}" stroke="{EDGE}" stroke-width="0.6"/>'


def activity_card(days, today):
    w, h = 1200, 300
    start = today - dt.timedelta(days=today.weekday() + 52 * 7)
    total = sum(v for d, v in days.items() if d >= start)
    active = sum(1 for d, v in days.items() if d >= start and v)
    cur, longest = streaks(days, today)
    peak = max([v for d, v in days.items() if d >= start] or [1])
    p = frame(w, h, "ACTIVITY/LAST/12M", f"codeberg · updated {today:%Y-%m-%d}")
    for i, (val, lab) in enumerate(
        [(total, "CONTRIBUTIONS"), (active, "ACTIVE DAYS"), (f"{cur}d", "CURRENT STREAK"), (f"{longest}d", "LONGEST STREAK")]
    ):
        p.append(stat(w - 32 - (4 - i) * 170, 48, val, lab))
    p.append(rule(84, w))
    x0, y0, step = 44, 140, 21.2
    cells, month = [], None
    for wk in range(53):
        for wd in range(7):
            d = start + dt.timedelta(days=wk * 7 + wd)
            if d > today:
                continue
            cells.append((wk, wd, d, days.get(d, 0)))
        first = start + dt.timedelta(days=wk * 7)
        if first.month != month:
            month = first.month
            if 0 < wk < 51 or (wk == 0 and first.day <= 14):
                p.append(
                    f'    <text x="{x0 + wk * step - 4}" y="{y0 - 22}" font-size="9" letter-spacing="2">{first:%b}</text>'.replace(
                        f"{first:%b}", f"{first:%b}".upper()
                    )
                )
    pos = {d: (round(x0 + wk * step, 1), round(y0 + wd * 21, 1)) for wk, wd, d, _ in cells}
    # lattice: link active days to the next day (same column) and to the same weekday next week
    p.append(f'    <g stroke="{BLUE}" stroke-opacity=".3" stroke-width="0.8">')
    for _, wd, d, v in cells:
        for nxt in ((d + dt.timedelta(days=1)) if wd < 6 else None, d + dt.timedelta(days=7)):
            if v and nxt in pos and days.get(nxt):
                (x1, y1), (x2, y2) = pos[d], pos[nxt]
                p.append(f'      <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')
    p.append("    </g>")
    for _, _, d, v in cells:
        x, y = pos[d]
        tip = f"<title>{d:%Y-%m-%d}: {v}</title>"
        if not v:
            p.append(f'    <circle cx="{x}" cy="{y}" r="1.6" fill="{EDGE}">{tip}</circle>')
            continue
        lvl = min(3, int(3 * v / peak)) if peak else 0
        col, r = ((VIOLET, 2.6), (BLUE, 3.2), (CYAN, 3.8), (CREAM, 4.6))[lvl]
        if lvl == 3:
            p.append(f'    <circle cx="{x}" cy="{y}" r="11" fill="{BLUE}" opacity=".18"/>')
        p.append(f'    <circle cx="{x}" cy="{y}" r="{r}" fill="{col}">{tip}</circle>')
    if today in pos:
        x, y = pos[today]
        p.append(
            f'    <circle cx="{x}" cy="{y}" r="4" fill="none" stroke="{CREAM}" stroke-width="1">'
            '<animate attributeName="r" values="4;12;4" dur="2.4s" repeatCount="indefinite"/>'
            '<animate attributeName="opacity" values="1;0;1" dur="2.4s" repeatCount="indefinite"/></circle>'
        )
    return close(p)


def best_rating(lc):
    perfs = lc.get("perfs", {})
    rated = [(k, v["rating"]) for k, v in perfs.items() if k != "puzzle" and v.get("games") and v.get("rating")]
    return max(rated, key=lambda kv: kv[1], default=("", 0))


def md(text):
    # escape what would otherwise turn into HTML or tables; markdown punctuation in profile.toml is left alone on purpose
    return escape(text).replace("|", "\\|")


def details(summary, body, open_=False):
    # blank lines around the body make Forgejo render it as markdown instead of plain text
    return f"<details{' open' if open_ else ''}>\n<summary>{summary}</summary>\n\n{body.strip()}\n\n</details>"


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---:" if i else "---" for i in range(len(header))) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def sparkline(values):
    # "·" marks a week without commits so a quiet repo reads as a flat dotted line, not a row of bars
    peak = max(values) or 1
    return "".join("▁▂▃▄▅▆▇█"[min(7, (8 * v - 1) // peak)] if v else "·" for v in values)


def project(e, r, history, active, first):
    url = e.get("url") or f"{FORGE}/{USER}/{e['repo']}"
    pills = " ".join(f"<code>{md(t)}</code>" for t in e.get("tags", []))
    status = "🟢 active" if active else "<em>archived</em>"
    summary = " · ".join(x for x in (f"<strong>{md(e['repo'])}</strong>", pills, status) if x)
    total, weekly, last = history
    rows = [("commits total", f"{total:,}")]
    if last:
        rows.append(("last commit", f"{last:%Y-%m-%d}"))
    if r.get("language"):
        rows.append(("language", r["language"].lower()))
    if r.get("stars_count"):
        rows.append(("★ stars", f"{r['stars_count']:,}"))
    if r.get("release_counter"):
        rows.append(("releases", r["release_counter"]))
    links = f"**Repo:** [{USER}/{md(e['repo'])}]({url})"
    if e.get("docs"):
        links += f" · **Docs:** [{md(e['docs'].split('://', 1)[1].rstrip('/'))}]({e['docs']})"
    stats = table(("commits · last 12 weeks", f"`{sparkline(weekly)}`"), rows)
    return details(summary, f"{e['text']}\n\n{stats}\n\n{links}", open_=first)


def readme(cfg, repo_list, history, days, today, lines, quadlets, tasks, lc):
    by_name = {r["name"].lower(): r for r in repo_list}
    t = cfg["transmission"]
    out = [
        "<!-- generated by scripts/stats.py from scripts/profile.toml; edit that file, not this one -->",
        f"# {md(cfg['name'])}",
        # trailing backslash is a hard line break; Forgejo joins plain newlines into one line
        f"**{md(t['lead'])}**\\\n{md(' '.join(t['body']))}",
        " · ".join(f"`{md(s)}`" for s in cfg["stack"]["items"]),
        "## Projects",
        f"<sub>{len(cfg['nodes'])} ACTIVE · {len(cfg['archive'])} ARCHIVED · ONE CLICK TO EXPAND</sub>",
    ]
    entries = [(e, True) for e in cfg["nodes"]] + [(e, False) for e in cfg["archive"]]
    for i, (e, active) in enumerate(entries):
        out.append(project(e, by_name.get(e["repo"].lower(), {}), history[e["repo"]], active, i == 0))

    last = max((d for d, v in days.items() if v), default=None)
    out += [
        "## Telemetry",
        "![Codeberg activity over the last 12 months](./assets/stats-activity.svg)",
        f"{len(repo_list)} public repos"
        + (f" · last push {last:%Y-%m-%d}" if last else "")
        + f" · rendered {today:%Y-%m-%d} from the Codeberg and Lichess APIs",
    ]

    total = sum(lines.values())
    top = lines.most_common(6)
    rows = [(lang.lower(), f"{n:,}", f"{100 * n / max(1, total):.0f}%") for lang, n in top]
    if rest := total - sum(n for _, n in top):
        rows.append(("other", f"{rest:,}", f"{100 * rest / max(1, total):.0f}%"))
    out.append(
        details(
            f"<strong>codebase</strong> · <code>{total:,} lines · {quadlets} quadlet units · {tasks:,} ansible tasks</code>",
            "Non-empty lines across my public repos.\n\n" + table(("language", "lines", "share"), rows),
        )
    )

    perfs, c = lc.get("perfs", {}), lc.get("count", {})
    variants = ("classical", "rapid", "blitz", "bullet", "correspondence", "puzzle")
    rows = [(k, perfs[k]["rating"], f"{perfs[k]['games']:,}") for k in variants if perfs.get(k, {}).get("games")]
    perf, rating = best_rating(lc)
    decided = c.get("win", 0) + c.get("loss", 0) + c.get("draw", 0)
    winrate = f"{100 * c.get('win', 0) / max(1, decided):.0f}%"
    out.append(
        details(
            "<strong>chess</strong> · <code>" + (f"best {rating} · {perf}" if rating else "unrated") + "</code>",
            table(("variant", "rating", "games"), rows)
            + f"\n\n{c.get('all', 0):,} games · {winrate} win rate · [@{LICHESS} on lichess](https://lichess.org/@/{LICHESS})",
        )
    )

    out.append("## Endpoints")
    groups = {}
    for e in cfg["endpoints"]:
        groups.setdefault(e.get("group", ""), []).append(f"{e['kind']}: [{md(e['label'])}]({e['url']})")
    out += [(f"**{md(g)}** — " if g else "") + " · ".join(items) for g, items in groups.items()]

    f = cfg["footer"]
    out += ["---", f'<sub><a href="{escape(f["url"], {chr(34): "&quot;"})}">{md(f["text"].lower())}</a></sub>']
    return "\n\n".join(out) + "\n"


def write(name, svg):
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {os.path.normpath(path)}")


def main():
    today = dt.datetime.now(TZ).date()
    rl = repos()
    days = heatmap()
    lines, quadlets, tasks = count_lines(rl)
    lc = get(f"https://lichess.org/api/user/{LICHESS}")
    with open(PROFILE, "rb") as f:
        cfg = tomllib.load(f)
    history = {e["repo"]: commits(e["repo"], today) for e in cfg["nodes"] + cfg["archive"]}
    write("stats-activity.svg", activity_card(days, today))
    with open(README, "w", encoding="utf-8") as f:
        f.write(readme(cfg, rl, history, days, today, lines, quadlets, tasks, lc))
    print("wrote README.md")


if __name__ == "__main__":
    main()
