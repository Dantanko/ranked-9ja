#!/usr/bin/env python3
"""ranking9ja site generator.

Run from the repo folder:   python build.py

It reads every categories/<slug>.json (the scoring method) and the matching
data/<slug>.json (the businesses), checks them, scores them, and writes:
  <slug>/index.html          ranked list
  <slug>/how-we-rank.html    the method, written from the config
  <slug>/<business>.html     one page per business
  categories.html            list of all categories
  how-we-rank.html           overview of the rules
Needs only Python 3, no installs.
"""
import glob
import html
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CSS_VERSION = "9"


def esc(s):
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------- page chrome
PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>[[T]] | ranking9ja</title>
<meta name="description" content="[[D]]">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="[[P]]assets/styles.css?v=[[V]]">
</head>
<body>
<header class="nav"><div class="wrap"><div class="bar"><a class="brand" href="[[P]]index.html">ranking<span>9ja</span></a>
<nav aria-label="Main"><a href="[[P]]categories.html">Categories</a><a href="[[P]]how-we-rank.html">How we rank</a><a href="[[P]]get-listed.html">Get listed</a><a href="[[P]]blog.html">Blog</a></nav></div></div></header>
<section class="band"><div class="wrap"><div class="hero slim"><h1>[[H1]]</h1><p>[[SUB]]</p></div></div></section>
<main class="wrap">
[[M]]
</main>
<footer><div class="wrap"><a href="[[P]]how-we-rank.html">How we rank</a><a href="[[P]]get-listed.html">Get listed</a><a href="[[P]]privacy.html">Privacy</a><a href="[[P]]write-for-us.html">Write for us</a></div></footer>
[[J]]</body>
</html>
"""

FILTER_JS = """<script>
document.querySelectorAll('.chips button').forEach(function(b){b.addEventListener('click',function(){var a=b.dataset.area;
document.querySelectorAll('.chips button').forEach(function(x){x.setAttribute('aria-pressed',x===b)});
document.querySelectorAll('.card').forEach(function(c){c.hidden=(a!=='all'&&c.dataset.area!==a)});});});
</script>
"""


def write_page(rel_path, title, desc, h1, sub, main, script=""):
    depth = rel_path.count("/")
    prefix = "../" * depth
    out = PAGE
    for key, val in (("[[T]]", esc(title)), ("[[D]]", esc(desc)), ("[[P]]", prefix),
                     ("[[V]]", CSS_VERSION), ("[[H1]]", h1), ("[[SUB]]", sub),
                     ("[[M]]", main), ("[[J]]", script)):
        out = out.replace(key, val)
    full = os.path.join(ROOT, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(out)


# ------------------------------------------------------------ scoring engine
def measure_max(m):
    t = m["type"]
    if t == "rating":
        return m["weight"]
    if t == "banded":
        return max(p for _, p in m["bands"])
    if t == "flags":
        return sum(i["points"] for i in m["items"])
    if t == "per_item":
        return m["points_each"] * m["max_items"]
    raise ValueError("unknown measure type: %s" % t)


def score_measure(m, biz):
    t = m["type"]
    inputs = biz.get("inputs", {})
    if t == "rating":
        r = inputs.get(m["id"], {})
        n, avg = r.get("count", 0), r.get("avg", 0)
        if n <= 0:
            return 0
        pc, pr = m.get("prior_count", 20), m.get("prior_rating", 4.0)
        corrected = (n * avg + pc * pr) / (n + pc)
        return round(corrected / 5 * m["weight"])
    if t == "banded":
        if m.get("from"):
            mid, key = m["from"].split(".")
            value = inputs.get(mid, {}).get(key, 0)
        else:
            value = inputs.get(m["id"], 0)
        for floor, pts in sorted(m["bands"], reverse=True):
            if value >= floor:
                return pts
        return 0
    if t == "flags":
        got = set(inputs.get(m["id"], []))
        return sum(i["points"] for i in m["items"] if i["id"] in got)
    if t == "per_item":
        return m["points_each"] * min(len(inputs.get(m["id"], [])), m["max_items"])
    raise ValueError("unknown measure type: %s" % t)


def rule_text(m):
    t = m["type"]
    if t == "rating":
        return ("Points = corrected rating divided by 5, times %d. We add %d pretend reviews of %.1f stars "
                "to every business, then work out the average again, so a business with only a few reviews "
                "moves toward the middle." % (m["weight"], m.get("prior_count", 20), m.get("prior_rating", 4.0)))
    if t == "banded":
        bands = sorted(m["bands"], reverse=True)
        parts, prev = [], None
        for floor, pts in bands:
            if prev is None:
                parts.append("%d or more: %d" % (floor, pts))
            elif floor == prev - 1:
                parts.append("%d: %d" % (floor, pts))
            else:
                parts.append("%d to %d: %d" % (floor, prev - 1, pts))
            prev = floor
        parts.append("None: 0" if prev == 1 else "Fewer than %d: 0" % prev)
        return ". ".join(parts) + "."
    if t == "flags":
        return " ".join("%d points if %s." % (i["points"], i["label"]) for i in m["items"])
    if t == "per_item":
        return "%d points for each, up to %d." % (m["points_each"], m["max_items"])
    return ""


def load_category(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    problems = []
    total = 0
    for m in cfg["measures"]:
        mx = measure_max(m)
        total += mx
        if m["type"] == "rating" and mx != m["weight"]:
            problems.append("%s: weight mismatch" % m["id"])
    if total != 100:
        problems.append("measures add up to %d, not 100" % total)
    if not cfg.get("gates"):
        problems.append("a category needs at least one gate")
    for m in cfg["measures"]:
        m["max"] = measure_max(m)
    return cfg, problems


def score_business(cfg, biz):
    lines, total = [], 0
    for m in cfg["measures"]:
        pts = score_measure(m, biz)
        total += pts
        lines.append((m, pts))
    passes = all(biz.get("gates", {}).get(g["id"], False) for g in cfg["gates"])
    count = biz.get("inputs", {}).get("rating", {}).get("count", 0)
    return {"biz": biz, "lines": lines, "total": total, "passes": passes,
            "ranked": passes and count >= cfg.get("min_verified_reviews", 10)}


# -------------------------------------------------------------- page pieces
def breakdown(lines):
    rows = ""
    for m, pts in lines:
        pct = round(pts / m["max"] * 100) if m["max"] else 0
        rows += ('<li><span>%s</span><span class="bar2"><span style="width:%d%%"></span></span>'
                 '<em>%d/%d</em></li>' % (esc(m["label"]), pct, pts, m["max"]))
    return '<ul class="break">%s</ul>' % rows


def stars(r):
    n = round(r)
    return "★" * n + "☆" * (5 - n)


def thumb(cfg, biz, prefix=""):
    if cfg.get("icon"):
        return '<div class="ph"><img src="%sassets/%s" alt="" width="46" height="46"></div>' % (prefix, esc(cfg["icon"]))
    return '<div class="ph"><b style="font-size:2rem;color:var(--teal)">%s</b></div>' % esc(biz["name"][:1])


def card(cfg, r, rank=None):
    b = r["biz"]
    rt = b.get("inputs", {}).get("rating", {})
    tag = '<span class="tag">Sample</span>' if b.get("sample") else ""
    name = '<a href="%s.html">%s</a>' % (esc(b["slug"]), esc(b["name"]))
    title = ("%d. %s" % (rank, name)) if rank else name
    chips = "".join("<span>%s</span>" % esc(h) for h in b.get("highlights", []))
    if r["ranked"]:
        meta = ('<p class="meta"><span class="stars">%s</span> %s, %d reviews on %s</p>'
                % (stars(rt.get("avg", 0)), rt.get("avg", 0), rt.get("count", 0), esc(rt.get("source", ""))))
        why = '<p class="meta">Why it ranks: %s</p>' % esc(b["why"]) if b.get("why") else ""
        score = '<div class="score"><b>%d</b><span>OF 100</span></div>' % r["total"]
        extra = "<details><summary>Score breakdown</summary>%s</details>" % breakdown(r["lines"])
    else:
        need = cfg.get("min_verified_reviews", 10)
        meta = ('<p class="meta">Rated by: %s. %d of %d verified reviews so far.</p>'
                % (esc(rt.get("source", "")), rt.get("count", 0), need))
        why, extra = "", ""
        score = '<div class="score off"><b>-</b><span>NOT RANKED</span></div>'
    return ('<li class="card" data-area="%s">%s<div class="info"><h3>%s%s</h3>%s'
            '<p class="meta">%s. Checked %s.</p>%s<p class="spec">%s</p></div>%s%s</li>'
            % (esc(b.get("area", "")), thumb(cfg, b), title, tag, meta, esc(b.get("location", "")),
               esc(b.get("checked", "")), why, chips, score, extra))


def category_index(cfg, results):
    ranked = sorted([r for r in results if r["ranked"]], key=lambda r: -r["total"])
    collecting = [r for r in results if r["passes"] and not r["ranked"]]
    areas = sorted({r["biz"].get("area") for r in ranked + collecting if r["biz"].get("area")})
    chips = '<button type="button" data-area="all" aria-pressed="true">All areas</button>' + "".join(
        '<button type="button" data-area="%s" aria-pressed="false">%s</button>' % (esc(a), esc(a)) for a in areas)
    main = '<section class="sec"><h2>Ranked %s in %s</h2>' % (esc(cfg["label"].lower()), esc(cfg["city"]))
    main += '<div class="chips" role="group" aria-label="Filter by area">%s</div>' % chips
    main += '<ol class="list">%s</ol>' % "".join(card(cfg, r, i) for i, r in enumerate(ranked, 1))
    if collecting:
        main += ('<h2 class="sub">Collecting reviews</h2><p class="meta">These are listed but not ranked yet. '
                 'A business is ranked once it has %d verified reviews from any source.</p><ol class="list">%s</ol>'
                 % (cfg.get("min_verified_reviews", 10), "".join(card(cfg, r) for r in collecting)))
    main += ('<aside class="sponsor" aria-label="Sponsored"><span class="tag">Sponsored</span>'
             '<p><strong>Want your %s here?</strong> Sponsored spots sit outside the ranking and never change it.</p>'
             '</aside></section>' % esc(cfg.get("singular", "business")))
    write_page("%s/index.html" % cfg["slug"], "%s in %s, ranked" % (cfg["label"], cfg["city"]),
               cfg["description"], "%s in %s" % (esc(cfg["label"]), esc(cfg["city"])),
               "Every rank shows its score and how it was worked out. Listings marked Sample are placeholders.",
               main, FILTER_JS)


def category_method(cfg):
    main = ('<section class="sec prose"><p>Every %s gets a score out of 100. We want you to see why one sits above '
            'another, so here is exactly how the points are earned. The same rules apply to every one.</p>'
            % esc(cfg.get("singular", "business")))
    for i, m in enumerate(cfg["measures"], 1):
        main += "<h2>%d. %s (up to %d points)</h2><p>%s</p>" % (i, esc(m["label"]), m["max"], esc(rule_text(m)))
        if m.get("note"):
            main += '<p class="note">%s</p>' % esc(m["note"])
    main += "<h2>Who gets ranked</h2>"
    main += "<p>Only if all of these are true. Otherwise it is not ranked at all, whatever its other numbers.</p><ol class=\"steps\">"
    main += "".join("<li>%s</li>" % esc(g["label"]) for g in cfg["gates"]) + "</ol>"
    main += ("<p>A business with fewer than %d verified reviews from any source is listed as Collecting reviews and "
             "ranked once it reaches that number. We confirm our own reviews on WhatsApp, allow one per phone number, "
             "and never let a business choose who is asked.</p>" % cfg.get("min_verified_reviews", 10))
    main += ('<h2>What cannot change a score</h2><p>Money. Listing is free. Paid profiles and sponsored spots sit outside '
             'the ranking and never move a business up or down.</p>'
             '<h2>Think a score is wrong?</h2><p>Contact us at [contact email to be added] and tell us what is wrong. '
             'We will check it and correct it if you are right.</p></section>')
    write_page("%s/how-we-rank.html" % cfg["slug"], "How we rank %s" % cfg["label"].lower(),
               "How the score works for %s in %s." % (cfg["label"].lower(), cfg["city"]),
               "How the score works", "Out of 100, in plain steps. Anyone can check the working.", main)


def business_page(cfg, r):
    b = r["biz"]
    rt = b.get("inputs", {}).get("rating", {})
    tag = '<span class="tag">Sample</span>' if b.get("sample") else ""
    score = ('<div class="score"><b>%d</b><span>OF 100</span></div>' % r["total"]) if r["ranked"] else \
            '<div class="score off"><b>-</b><span>NOT RANKED</span></div>'
    main = '<section class="sec"><p class="meta"><a href="index.html">%s in %s</a></p>' % (esc(cfg["label"]), esc(cfg["city"]))
    main += ('<div class="card" style="margin-top:1rem">%s<div class="info"><h1 style="font-size:1.9rem">%s%s</h1>'
             '<p class="meta"><span class="stars">%s</span> %s, %d reviews on %s. %s. Last checked %s.</p></div>%s</div></section>'
             % (thumb(cfg, b, "../"), esc(b["name"]), tag, stars(rt.get("avg", 0)), rt.get("avg", 0), rt.get("count", 0),
                esc(rt.get("source", "")), esc(b.get("location", "")), esc(b.get("checked", "")), score))
    main += '<section class="prose"><h2>How this score adds up</h2>%s' % breakdown(r["lines"])
    main += '<p class="note"><a href="how-we-rank.html">How we rank</a>. Sample data where marked.</p>'
    for m in cfg["measures"]:
        got = set(b.get("inputs", {}).get(m["id"], [])) if m["type"] in ("flags", "per_item") else set()
        if not got:
            continue
        if m["type"] == "flags":
            items = [i["label"] for i in m["items"] if i["id"] in got]
        else:
            items = sorted(got)
        main += "<h2>%s</h2><ul class=\"steps\">%s</ul>" % (esc(m["label"]), "".join("<li>%s</li>" % esc(x) for x in items))
    main += "</section>"
    write_page("%s/%s.html" % (cfg["slug"], b["slug"]), "%s, %s" % (b["name"], b.get("location", "")),
               "%s score breakdown and checks." % b["name"], "Profile", "Score, method and checks in one place.", main)


def top_pages(cats):
    cards = ""
    for cfg, results in cats:
        n = sum(1 for r in results if r["ranked"])
        cards += ('<div class="cat"><h3>%s in %s</h3><p>%s</p><div class="chips-sm"><a href="%s/index.html">See ranking</a>'
                  '<a href="%s/how-we-rank.html">How it is scored</a></div><p class="meta">%d ranked so far.</p></div>'
                  % (esc(cfg["label"]), esc(cfg["city"]), esc(cfg["description"]), esc(cfg["slug"]), esc(cfg["slug"]), n))
    main = '<section class="sec"><div class="cats">%s<div class="cat muted"><h3>More categories coming</h3><p>Each new category gets its own method, checked by someone who knows the field.</p></div></div></section>' % cards
    write_page("categories.html", "Categories", "All ranking categories on ranking9ja.", "Categories",
               "Every category has its own method, built around what can be proved.", main)
    links = "".join('<li><a href="%s/how-we-rank.html">%s in %s</a></li>' % (esc(c["slug"]), esc(c["label"]), esc(c["city"])) for c, _ in cats)
    main = ('<section class="sec prose"><p>Every category on ranking9ja has its own method, but the same rules sit underneath all of them.</p>'
            '<h2>The rules for every category</h2><ol class="steps">'
            '<li>What a business can prove counts for more than what people say about it. The less reviews can tell us, the less they count.</li>'
            '<li>Only evidence we have seen or confirmed scores. A business\'s own claim earns nothing.</li>'
            '<li>Each category has gates. A business that fails a gate is not ranked at all, whatever its score.</li>'
            '<li>Every score is out of 100, and every point is explained on the business page.</li>'
            '<li>Money cannot change a score. Listing is free. Paid profiles and sponsored spots sit outside the ranking.</li>'
            '<li>A new category goes live only after someone who knows the field has checked its method.</li></ol>'
            '<h2>Methods by category</h2><ul class="steps">%s</ul></section>' % links)
    write_page("how-we-rank.html", "How we rank", "The rules behind every ranking on ranking9ja.",
               "How we rank", "The rules every category follows.", main)


def main():
    cats, bad = [], False
    for path in sorted(glob.glob(os.path.join(ROOT, "categories", "*.json"))):
        cfg, problems = load_category(path)
        if problems:
            bad = True
            print("PROBLEM in %s: %s" % (os.path.basename(path), "; ".join(problems)))
            continue
        data_path = os.path.join(ROOT, "data", cfg["slug"] + ".json")
        businesses = json.load(open(data_path, encoding="utf-8")) if os.path.exists(data_path) else []
        results = [score_business(cfg, b) for b in businesses]
        for r in results:
            if not r["passes"]:
                print("  excluded (gate failed): %s" % r["biz"]["name"])
        shown = [r for r in results if r["passes"]]
        category_index(cfg, shown)
        category_method(cfg)
        for r in shown:
            business_page(cfg, r)
        cats.append((cfg, shown))
        print("%s: %d ranked, %d collecting reviews" % (cfg["slug"], sum(1 for r in shown if r["ranked"]),
                                                       sum(1 for r in shown if not r["ranked"])))
        for r in sorted(shown, key=lambda r: -r["total"]):
            print("   %3d  %s%s" % (r["total"], r["biz"]["name"], "" if r["ranked"] else "  (not ranked)"))
    if bad:
        sys.exit("Fix the problems above, then run build.py again.")
    top_pages(cats)
    print("Done.")


if __name__ == "__main__":
    main()
