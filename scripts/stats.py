#!/usr/bin/env python3
"""Render the profile stat cards in assets/ from Codeberg and Lichess data.

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

BG0, BG1 = "#0b1020", "#111a2e"
GRID = "#2b3a5c"
TEXT = "#e6edf7"
MUTED = "#8b9bb4"
ACCENT = "#4fd1c5"
BLUE = "#7aa2f7"
FONT = "ui-monospace, 'JetBrains Mono', 'Fira Code', Menlo, Consolas, monospace"

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
LANG_COLOR = {
    "YAML": "#cb4b4b",
    "Jinja": "#a52a22",
    "Shell": "#89e051",
    "Python": "#3572a5",
    "Nushell": "#4e9906",
    "Lua": "#6c78d8",
    "Terraform": "#7b42bc",
    "Quadlet": "#892ca0",
    "HTML": "#e34c26",
    "CSS": "#663399",
    "JavaScript": "#f1e05a",
    "TOML": "#9c4221",
    "Config": "#d1dbe0",
    "GLSL": "#5686a5",
    "Dockerfile": "#384d54",
}
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
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-labelledby="t">',
        f'  <title id="t">{escape(title)}{escape(" — " + subtitle) if subtitle else ""}</title>',
        "  <defs>",
        f'    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BG0}"/><stop offset="1" stop-color="{BG1}"/></linearGradient>',
        "  </defs>",
        f'  <rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="12" fill="url(#bg)" stroke="{GRID}"/>',
        f'  <g font-family="{FONT}">',
        f'    <text x="28" y="40" font-size="15" fill="{ACCENT}" letter-spacing="2">// {escape(title)}</text>',
        f'    <text x="{w - 28}" y="40" font-size="12" fill="{MUTED}" text-anchor="end">{escape(subtitle)}</text>' if subtitle else "",
    ]


def close(parts):
    return "\n".join(p for p in parts if p) + "\n  </g>\n</svg>\n"


def stat(x, y, value, label, color=TEXT):
    return (
        f'    <text x="{x}" y="{y}" font-size="26" font-weight="700" fill="{color}">{escape(str(value))}</text>\n'
        f'    <text x="{x}" y="{y + 20}" font-size="11" fill="{MUTED}" letter-spacing="1">{escape(label)}</text>'
    )


def activity_card(days, n_repos, today):
    w, h = 1200, 290
    start = today - dt.timedelta(days=today.weekday() + 52 * 7)
    total = sum(v for d, v in days.items() if d >= start)
    active = sum(1 for d, v in days.items() if d >= start and v)
    cur, longest = streaks(days, today)
    peak = max([v for d, v in days.items() if d >= start] or [1])
    p = frame(w, h, "activity · last 12 months", f"updated {today:%Y-%m-%d}")
    for i, (val, lab, col) in enumerate(
        [
            (total, "CONTRIBUTIONS", TEXT),
            (active, "ACTIVE DAYS", TEXT),
            (f"{cur}d", "CURRENT STREAK", ACCENT),
            (f"{longest}d", "LONGEST STREAK", TEXT),
            (n_repos, "PUBLIC REPOS", BLUE),
        ]
    ):
        p.append(stat(28 + i * 165, 86, val, lab, col))
    x0, y0, step = 40, 150, 21.4
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
                p.append(f'    <text x="{x0 + wk * step - 4}" y="{y0 - 14}" font-size="10" fill="{MUTED}">{first:%b}</text>')
    pos = {d: (round(x0 + wk * step, 1), round(y0 + wd * step * 0.85, 1)) for wk, wd, d, _ in cells}
    p.append(f'    <g stroke="{ACCENT}" stroke-opacity=".28" stroke-width="1">')
    for _, wd, d, v in cells:
        for nxt in ((d + dt.timedelta(days=1)) if wd < 6 else None, d + dt.timedelta(days=7)):
            if v and nxt in pos and days.get(nxt):
                (x1, y1), (x2, y2) = pos[d], pos[nxt]
                p.append(f'      <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')
    p.append("    </g>")
    for _, _, d, v in cells:
        x, y = pos[d]
        if not v:
            p.append(f'    <circle cx="{x}" cy="{y}" r="2" fill="{GRID}"/>')
            continue
        lvl = min(4, 1 + int(3 * v / peak + 0.5)) if peak else 1
        r = (3, 4.2, 5.4, 6.6)[lvl - 1]
        col = ("#2c7a7b", "#38b2ac", ACCENT, "#b2f5ea")[lvl - 1]
        p.append(f'    <circle cx="{x}" cy="{y}" r="{r}" fill="{col}"><title>{d:%Y-%m-%d}: {v}</title></circle>')
    if today in pos:
        x, y = pos[today]
        p.append(
            f'    <circle cx="{x}" cy="{y}" r="4" fill="none" stroke="{TEXT}" stroke-width="1.5">'
            '<animate attributeName="r" values="4;11;4" dur="2.4s" repeatCount="indefinite"/>'
            '<animate attributeName="opacity" values="1;0;1" dur="2.4s" repeatCount="indefinite"/></circle>'
        )
    return close(p)


def code_card(lines, n_repos, quadlets, tasks):
    w, h = 590, 320
    top = lines.most_common(7)
    total = sum(lines.values()) or 1
    p = frame(w, h, "codebase · lines by language")
    x, bw, y = 28, w - 56, 62
    for lang, n in top:
        seg = bw * n / total
        p.append(f'    <rect x="{x:.1f}" y="{y}" width="{max(seg, 2):.1f}" height="10" fill="{LANG_COLOR.get(lang, MUTED)}"/>')
        x += seg
    rest = total - sum(n for _, n in top)
    if rest:
        p.append(f'    <rect x="{x:.1f}" y="{y}" width="{bw * rest / total:.1f}" height="10" fill="{GRID}"/>')
    for i, (lang, n) in enumerate(top):
        cx, cy = 28 + (i % 2) * 270, 102 + (i // 2) * 30
        p.append(f'    <circle cx="{cx + 5}" cy="{cy - 4}" r="5" fill="{LANG_COLOR.get(lang, MUTED)}"/>')
        p.append(f'    <text x="{cx + 18}" y="{cy}" font-size="13" fill="{TEXT}">{escape(lang)}</text>')
        p.append(f'    <text x="{cx + 230}" y="{cy}" font-size="12" fill="{MUTED}" text-anchor="end">{n:,} · {100 * n / total:.0f}%</text>')
    p.append(f'    <line x1="28" y1="230" x2="{w - 28}" y2="230" stroke="{GRID}"/>')
    for i, (val, lab, col) in enumerate(
        [(f"{total:,}", "LINES", TEXT), (quadlets, "QUADLET UNITS", ACCENT), (f"{tasks:,}", "ANSIBLE TASKS", BLUE)]
    ):
        p.append(stat(28 + i * 185, 268, val, lab, col))
    return close(p)


def chess_card(lc):
    w, h = 590, 320
    perfs = lc.get("perfs", {})
    rows = [(k, perfs[k]) for k in ("classical", "rapid", "blitz", "bullet", "correspondence", "puzzle") if perfs.get(k, {}).get("games")]
    p = frame(w, h, "chess · lichess", f"@{LICHESS}")
    lo, hi = 800, 2200
    best = max((v["rating"] for k, v in rows if k != "puzzle"), default=0)
    for i, (k, v) in enumerate(rows):
        y = 74 + i * 26
        frac = max(0, min(1, (v["rating"] - lo) / (hi - lo)))
        col = ACCENT if v["rating"] == best else (BLUE if k == "puzzle" else "#3d5a80")
        p.append(f'    <text x="28" y="{y + 9}" font-size="12" fill="{MUTED}">{k}</text>')
        p.append(f'    <rect x="160" y="{y}" width="290" height="10" rx="5" fill="{GRID}" opacity=".6"/>')
        p.append(f'    <rect x="160" y="{y}" width="{290 * frac:.1f}" height="10" rx="5" fill="{col}"/>')
        p.append(f'    <text x="{w - 28}" y="{y + 9}" font-size="13" fill="{TEXT}" text-anchor="end">{v["rating"]}</text>')
    c = lc.get("count", {})
    p.append(f'    <line x1="28" y1="230" x2="{w - 28}" y2="230" stroke="{GRID}"/>')
    played = c.get("all", 0)
    winrate = f"{100 * c.get('win', 0) / max(1, c.get('win', 0) + c.get('loss', 0) + c.get('draw', 0)):.0f}%"
    for i, (val, lab, col) in enumerate([(played, "GAMES", TEXT), (winrate, "WIN RATE", ACCENT), (best, "BEST RATING", BLUE)]):
        p.append(stat(28 + i * 185, 268, val, lab, col))
    return close(p)


def write(name, svg):
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {os.path.normpath(path)}")


def main():
    today = dt.datetime.now(TZ).date()
    rl = repos()
    write("stats-activity.svg", activity_card(heatmap(), len(rl), today))
    lines, quadlets, tasks = count_lines(rl)
    write("stats-code.svg", code_card(lines, len(rl), quadlets, tasks))
    write("stats-chess.svg", chess_card(get(f"https://lichess.org/api/user/{LICHESS}")))


if __name__ == "__main__":
    main()
