#!/usr/bin/env python3
"""Render the profile banner and stat cards in assets/ from Codeberg and Lichess data.

Stdlib only. Needs git on PATH. Usage: python3 scripts/stats.py
"""

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time
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
SERIES = (BLUE, VIOLET, CREAM, CYAN, "#c4b5fd", "#4ade80", "#64748b")
BANNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "banner.svg.in")

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


def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"{USER}-profile-stats", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
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


def code_card(lines, quadlets, tasks):
    w, h = 590, 320
    top = lines.most_common(6)
    total = sum(lines.values()) or 1
    p = frame(w, h, "CODEBASE/LINES", "non-empty lines across public repos")
    x, bw, y = 32, w - 64, 82
    for i, (_, n) in enumerate(top):
        seg = bw * n / total
        p.append(f'    <rect x="{x:.1f}" y="{y}" width="{max(seg - 2, 1):.1f}" height="6" fill="{SERIES[i]}"/>')
        x += seg
    rest = total - sum(n for _, n in top)
    if rest:
        p.append(f'    <rect x="{x:.1f}" y="{y}" width="{bw * rest / total:.1f}" height="6" fill="{EDGE}"/>')
    for i, (lang, n) in enumerate(top):
        cx, cy = 32 + (i % 2) * 270, 118 + (i // 2) * 24
        p.append(f'    <circle cx="{cx + 3}" cy="{cy - 4}" r="3.4" fill="{SERIES[i]}"/>')
        p.append(f'    <text x="{cx + 16}" y="{cy}" font-size="11">{escape(lang.lower())}</text>')
        p.append(f'    <text x="{cx + 236}" y="{cy}" font-size="11" fill="{CREAM}" text-anchor="end">{100 * n / total:.0f}%</text>')
    p.append(rule(212, w))
    for i, (val, lab) in enumerate([(f"{total:,}", "LINES"), (quadlets, "QUADLET UNITS"), (f"{tasks:,}", "ANSIBLE TASKS")]):
        p.append(stat(32 + i * 180, 254, val, lab))
    return close(p)


def chess_card(lc):
    w, h = 590, 320
    perfs = lc.get("perfs", {})
    rows = [(k, perfs[k]) for k in ("classical", "rapid", "blitz", "bullet", "correspondence", "puzzle") if perfs.get(k, {}).get("games")]
    p = frame(w, h, "CHESS/LICHESS", f"@{LICHESS} · ratings")
    lo, hi = 800, 2200
    best = best_rating(lc)
    for i, (k, v) in enumerate(rows):
        y = 84 + i * 21
        frac = max(0, min(1, (v["rating"] - lo) / (hi - lo)))
        col = CREAM if v["rating"] == best[1] and k == best[0] else (VIOLET if k == "puzzle" else BLUE)
        p.append(f'    <text x="32" y="{y + 7}" font-size="11">{k}</text>')
        p.append(f'    <line x1="170" y1="{y + 3}" x2="470" y2="{y + 3}" stroke="{EDGE}" stroke-width="1"/>')
        p.append(f'    <line x1="170" y1="{y + 3}" x2="{170 + 300 * frac:.1f}" y2="{y + 3}" stroke="{col}" stroke-width="2"/>')
        p.append(f'    <circle cx="{170 + 300 * frac:.1f}" cy="{y + 3}" r="3.2" fill="{col}"/>')
        p.append(f'    <text x="{w - 32}" y="{y + 7}" font-size="11" fill="{CREAM}" text-anchor="end">{v["rating"]}</text>')
    c = lc.get("count", {})
    p.append(rule(212, w))
    decided = c.get("win", 0) + c.get("loss", 0) + c.get("draw", 0)
    winrate = f"{100 * c.get('win', 0) / max(1, decided):.0f}%"
    for i, (val, lab) in enumerate([(c.get("all", 0), "GAMES"), (winrate, "WIN RATE"), (best[1], "BEST RATING")]):
        p.append(stat(32 + i * 180, 254, val, lab))
    return close(p)


def best_rating(lc):
    perfs = lc.get("perfs", {})
    rated = [(k, v["rating"]) for k, v in perfs.items() if k != "puzzle" and v.get("games") and v.get("rating")]
    return max(rated, key=lambda kv: kv[1], default=("", 0))


def banner(n_repos, days, today, quadlets, tasks, lc):
    start = today - dt.timedelta(days=365)
    last = max((d for d, v in days.items() if v), default=None)
    cur, _ = streaks(days, today)
    perf, rating = best_rating(lc)
    short = {"correspondence": "corr"}.get(perf, perf)
    values = {
        "version": f"{today:%Y.%m}",
        "stat_repos": str(n_repos),
        "stat_contributions": f"{sum(v for d, v in days.items() if d > start):,}",
        "stat_quadlets": str(quadlets),
        "stat_tasks": f"{tasks:,}",
        "stat_chess": f"{rating} · {short}" if rating else "—",
        "status": f"LAST PUSH {last:%Y-%m-%d} · STREAK {cur}D · TZ EUROPE/BERLIN" if last else "TZ EUROPE/BERLIN",
    }
    with open(BANNER, encoding="utf-8") as f:
        svg = f.read()
    for k, v in values.items():
        svg = svg.replace("{{" + k + "}}", escape(v))
    svg = svg.replace("{{tokens}} are filled", "values are filled")
    return svg


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
    write("neural-pulse-lattice.svg", banner(len(rl), days, today, quadlets, tasks, lc))
    write("stats-activity.svg", activity_card(days, today))
    write("stats-code.svg", code_card(lines, quadlets, tasks))
    write("stats-chess.svg", chess_card(lc))


if __name__ == "__main__":
    main()
