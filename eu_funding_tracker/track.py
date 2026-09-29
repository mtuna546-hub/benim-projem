#!/usr/bin/env python3
"""EU Funding & Tenders Portal tracker with academic / ecosystem matching.

Pulls every OPEN and FORTHCOMING grant topic from the portal's public SEDIA
search API once, then scores every call against each profile in PROFILES:
the Engineering Faculty (profile_muhendislik.json) and the whole university
(profile.json). Each profile has its own focus areas, optional programme
weights and state file; ecosystem partners (İTO, Teknopark İstanbul, BTM),
academics (academics.csv) and Turkey notes are shared. Writes a Turkish HTML +
Markdown report per profile plus one combined GitHub issue body
(reports/issue-DATE.md): the engineering summary first, the general report in
a collapsible section below it.

    python3 track.py                 # all profiles
    python3 track.py --profile profile.json   # a single profile
    python3 track.py --email         # also send the first profile's report via SMTP
    python3 track.py --fixture f.json  # offline run against a saved API response

SMTP settings come from the environment: SMTP_HOST (default smtp.gmail.com),
SMTP_PORT (default 465), SMTP_USER, SMTP_PASSWORD, REPORT_TO.
"""

import argparse
import csv
import html
import json
import os
import re
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

import requests

HERE = Path(__file__).parent
PROFILE_PATH = HERE / "profile.json"  # base profile: ecosystem + Turkey notes live here
# Order matters: the first profile leads the combined issue, the rest are collapsed below it.
PROFILES = ["profile_muhendislik.json", "profile.json"]
ISSUE_BODY_LIMIT = 60000  # GitHub caps issue bodies at 65536 characters
ACADEMICS_PATH = HERE / "academics.csv"
REPORTS_DIR = HERE / "reports"

ENDPOINT = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
API_KEY = "SEDIA"
TYPE_GRANTS = ["1", "2", "8"]
STATUS_FORTHCOMING = "31094501"
STATUS_OPEN = "31094502"
STATUS_LABELS = {STATUS_OPEN: "Açık", STATUS_FORTHCOMING: "Yakında açılacak"}
PAGE_SIZE = 100
MAX_PAGES = 40
TOPIC_URL = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{}"

# A call is reported only if its focus-area score reaches MIN_AREA_SCORE AND at
# least one focus-area keyword appears in its title. Description hits are capped
# per keyword list so long, jargon-heavy call texts do not inflate the score.
MIN_AREA_SCORE = 6
BODY_SCORE_CAP = 3
MAX_ACADEMICS_PER_CALL = 5
UPCOMING_DAYS = 30
SUMMARY_NEW = 25       # detailed new calls in the short summary (GitHub issue)
SUMMARY_BEST = 10      # best-matching open calls, new or not
SUMMARY_UPCOMING = 40  # deadline list length in the summary

PROGRAMME_LABELS = {
    "43108390": "Horizon Europe",
    "31045243": "Horizon 2020",
    "43252405": "LIFE",
    "43353764": "Erasmus+",
    "43251814": "Creative Europe",
    "43152860": "Digital Europe Programme",
    "43251567": "Connecting Europe Facility",
    "43332642": "EU4Health",
    "43251589": "Citizens, Equality, Rights and Values",
    "43089234": "Innovation Fund",
    "43392145": "European Maritime, Fisheries and Aquaculture Fund",
}

# Fallback when the numeric programme id is unknown: topic identifiers start
# with the programme's abbreviation (e.g. "EDF-2026-...", "SMP-COSME-...").
IDENTIFIER_PREFIX_LABELS = {
    "HORIZON": "Horizon Europe",
    "DIGITAL": "Digital Europe Programme",
    "LIFE": "LIFE",
    "ERASMUS": "Erasmus+",
    "CREA": "Creative Europe",
    "CEF": "Connecting Europe Facility",
    "EU4H": "EU4Health",
    "CERV": "Citizens, Equality, Rights and Values",
    "INNOVFUND": "Innovation Fund",
    "EMFAF": "European Maritime, Fisheries and Aquaculture Fund",
    "EDF": "European Defence Fund",
    "SMP": "Single Market Programme",
    "I3": "Interregional Innovation Investments",
    "EUAF": "Union Anti-Fraud Programme",
    "JUST": "Justice Programme",
    "AMIF": "Asylum, Migration and Integration Fund",
    "ISF": "Internal Security Fund",
    "BMVI": "Border Management and Visa Instrument",
    "RFCS": "Research Fund for Coal and Steel",
    "UCPM": "Union Civil Protection Mechanism",
    "EUBA": "European Union Bodies and Agencies",
    "PPPA": "Pilot Projects and Preparatory Actions",
    "SOCPL": "Social Prerogative and Specific Competencies",
    "EURATOM": "Euratom Research and Training Programme",
    "RENEWFM": "Renewable Energy Financing Mechanism",
}


def programme_label(programme_id, identifier):
    if programme_id in PROGRAMME_LABELS:
        return PROGRAMME_LABELS[programme_id]
    prefix = (identifier or "").split("-")[0].upper()
    return IDENTIFIER_PREFIX_LABELS.get(prefix, programme_id)


# --------------------------------------------------------------------------- API

def search_page(page_number, statuses):
    query = {
        "bool": {
            "must": [
                {"terms": {"type": TYPE_GRANTS}},
                {"terms": {"status": statuses}},
            ]
        }
    }
    # The upstream API requires POST multipart/form-data where every part
    # carries Content-Type: application/json, or it answers HTTP 500.
    files = {
        "query": (None, json.dumps(query), "application/json"),
        "languages": (None, json.dumps(["en"]), "application/json"),
        "sort": (None, json.dumps({"field": "deadlineDate", "order": "ASC"}), "application/json"),
    }
    params = {
        "apiKey": API_KEY,
        "text": "***",
        "pageSize": str(PAGE_SIZE),
        "pageNumber": str(page_number),
    }
    resp = requests.post(
        ENDPOINT, params=params, files=files, headers={"Accept": "application/json"}, timeout=60
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("type") == "throwable":
        raise RuntimeError(f"SEDIA API error: {data.get('message')}")
    return data


def fetch_all_hits():
    hits = []
    for page in range(1, MAX_PAGES + 1):
        results = search_page(page, [STATUS_OPEN, STATUS_FORTHCOMING]).get("results") or []
        hits.extend(results)
        if len(results) < PAGE_SIZE:
            break
    return hits


def values(meta, key):
    """Every metadata value the API returns is wrapped in a list."""
    v = (meta or {}).get(key)
    if v is None:
        return []
    return [str(x) for x in v] if isinstance(v, list) else [str(v)]


def one(meta, key):
    vs = values(meta, key)
    return vs[0] if vs else None


def strip_html(text):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def parse_calls(hits):
    calls, seen = [], set()
    for hit in hits:
        meta = hit.get("metadata") or {}
        identifier = one(meta, "identifier")
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        programme_id = one(meta, "frameworkProgramme")
        title = one(meta, "title") or hit.get("title") or identifier
        body = " ".join(
            [one(meta, "callTitle") or ""]
            + values(meta, "keywords")
            + values(meta, "tags")
            + [strip_html(one(meta, "descriptionByte")), strip_html(hit.get("summary"))]
        )
        calls.append(
            {
                "identifier": identifier,
                "title": title,
                "call_title": one(meta, "callTitle"),
                "deadline": (one(meta, "deadlineDate") or "")[:10] or None,
                "status": STATUS_LABELS.get(one(meta, "status"), one(meta, "status")),
                "programme": programme_label(programme_id, identifier),
                "url": one(meta, "url") or hit.get("url") or TOPIC_URL.format(identifier.lower()),
                "title_text": title.lower(),
                "body_text": body.lower(),
            }
        )
    return calls


# ---------------------------------------------------------------------- matching

def load_profile(path=PROFILE_PATH):
    """Load a profile; missing ecosystem / Turkey notes are inherited from profile.json."""
    profile = json.loads(Path(path).read_text(encoding="utf-8"))
    if Path(path).resolve() != PROFILE_PATH.resolve():
        base = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        for key in ("ecosystem", "turkey_participation"):
            profile.setdefault(key, base.get(key, {}))
    return profile


def programme_weight(call, profile):
    """Sum of profile["programme_weights"] whose regex matches the call identifier."""
    ident = call["identifier"].upper()
    return sum(w for pattern, w in profile.get("programme_weights", {}).items()
               if re.search(pattern, ident))


def load_academics(path=ACADEMICS_PATH):
    if not path.exists():
        return []
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    split = lambda s: [x.strip() for x in (s or "").split(";") if x.strip()]
    return [
        {
            "name": row["name"].strip(),
            "department": (row.get("department") or "").strip(),
            "email": (row.get("email") or "").strip(),
            "focus_areas": split(row.get("focus_areas")),
            "keywords": [k.lower() for k in split(row.get("keywords"))],
        }
        for row in csv.DictReader(lines)
        if (row.get("name") or "").strip()
    ]


def keyword_hits(call, keywords):
    """Return (score, matched keywords, title_hit).

    A hit in the title counts 3; hits elsewhere count 1 each, capped at
    BODY_SCORE_CAP for the whole keyword list.
    """
    title_score, body_score, matched = 0, 0, []
    for kw in keywords:
        pattern = r"\b" + re.escape(kw.lower()) + r"\b"
        if re.search(pattern, call["title_text"]):
            title_score += 3
            matched.append(kw)
        elif re.search(pattern, call["body_text"]):
            body_score += 1
            matched.append(kw)
    return title_score + min(body_score, BODY_SCORE_CAP), matched, title_score > 0


def match_call(call, profile, academics):
    areas, title_hit = [], False
    for area in profile["focus_areas"]:
        score, matched, in_title = keyword_hits(call, area["keywords"])
        title_hit = title_hit or in_title
        if score:
            areas.append({"id": area["id"], "name": area["name"], "score": score, "matched": matched})
    areas.sort(key=lambda a: -a["score"])
    area_scores = {a["id"]: a["score"] for a in areas}

    people = []
    for ac in academics:
        own, matched, _ = keyword_hits(call, ac["keywords"])
        via_area = max((area_scores.get(a, 0) for a in ac["focus_areas"]), default=0)
        score = own * 2 + via_area
        if score:
            people.append({**ac, "score": score, "matched": matched})
    people.sort(key=lambda p: -p["score"])

    ecosystem = []
    for partner in profile["ecosystem"]:
        score, matched, _ = keyword_hits(call, partner["keywords"])
        if score:
            ecosystem.append({**partner, "score": score, "matched": matched})
    ecosystem.sort(key=lambda e: -e["score"])

    weight = programme_weight(call, profile)
    total = sum(a["score"] for a in areas) + weight
    return {
        "total": total,
        "weight": weight,
        "title_hit": title_hit,
        "areas": areas[:3],
        "academics": people[:MAX_ACADEMICS_PER_CALL],
        "ecosystem": ecosystem,
    }


def turkey_note(profile, programme):
    notes = profile.get("turkey_participation", {})
    return notes.get(programme or "", notes.get("_default", ""))


# ------------------------------------------------------------------------ report

def build_report(new_matches, best, upcoming, profile, academics_count, stats, summary=False):
    """Render the report. summary=True gives the short version used for the GitHub issue."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = f"AB Fon Çağrıları — {profile['institution']} Eşleştirme Raporu ({today})"
    md = [f"# {title}", ""]
    md.append(
        f"Taranan açık/yakında açılacak çağrı: **{stats['scanned']}** · "
        f"Kurumla eşleşen: **{stats['matched']}** · Yeni: **{len(new_matches)}** · "
        f"Kayıtlı akademisyen: **{academics_count}**"
    )
    if academics_count == 0:
        md.append(
            "\n> Not: `academics.csv` henüz boş; eşleştirmeler şimdilik odak alanı düzeyinde. "
            "Akademisyen eklendiğinde kişi bazlı öneriler de görünecek."
        )
    md.append("")

    def call_md(call, m):
        out = [f"### {call['title']}"]
        out.append(f"- **Kod:** `{call['identifier']}` · **Program:** {call['programme'] or '-'} · **Durum:** {call['status'] or '-'}")
        weight = f" (program ağırlığı {m['weight']:+d})" if m.get("weight") else ""
        out.append(f"- **Son başvuru:** {call['deadline'] or 'Belirtilmemiş'} · **Uygunluk puanı:** {m['total']}{weight}")
        out.append(f"- **Türkiye:** {turkey_note(profile, call['programme'])}")
        out.append("- **Odak alanları:** " + "; ".join(f"{a['name']} ({', '.join(a['matched'][:4])})" for a in m["areas"]))
        if m["academics"]:
            out.append("- **Önerilen akademisyenler:** " + "; ".join(
                f"{p['name']} – {p['department']}" + (f" ({', '.join(p['matched'][:3])})" if p["matched"] else "")
                for p in m["academics"]))
        if m["ecosystem"]:
            out.append("- **Ekosistem ortakları:** " + "; ".join(f"{e['name']}: {e['role']}" for e in m["ecosystem"]))
        out.append(f"- **Bağlantı:** {call['url']}")
        out.append("")
        return out

    def line_md(call, m, lead):
        eco = ", ".join(e["name"] for e in m["ecosystem"]) or "-"
        return f"- **{lead}** — [{call['title']}]({call['url']}) (`{call['identifier']}`, puan {m['total']}, ekosistem: {eco})"

    shown_new = new_matches[:profile.get("summary_new", SUMMARY_NEW)] if summary else new_matches
    md.append(f"## Yeni eşleşen çağrılar ({len(new_matches)})\n")
    if not new_matches:
        md.append("Bu dönemde kurum profiliyle eşleşen yeni bir çağrı bulunamadı.\n")
    for call, m in shown_new:
        md += call_md(call, m)
    if len(new_matches) > len(shown_new):
        md.append(f"_…ve {len(new_matches) - len(shown_new)} yeni çağrı daha: tam rapora bakın._\n")

    if summary and best:
        md.append(f"## En uygun açık çağrılar (ilk {len(best)}, yeni olsun olmasın)\n")
        for call, m in best:
            md.append(line_md(call, m, call["deadline"] or "tarih yok"))
        md.append("")

    shown_up = upcoming[:SUMMARY_UPCOMING] if summary else upcoming
    md.append(f"## Son başvurusu {UPCOMING_DAYS} gün içinde olan eşleşen çağrılar ({len(upcoming)})\n")
    if not upcoming:
        md.append("Yok.\n")
    for call, m in shown_up:
        md.append(line_md(call, m, call["deadline"]))
    if len(upcoming) > len(shown_up):
        md.append(f"- _…ve {len(upcoming) - len(shown_up)} çağrı daha: tam rapora bakın._")
    md.append("")
    md.append("---\nOtomatik olarak EU Funding & Tenders Portal verisinden üretilmiştir; "
              "uygunluk ve Türkiye katılım bilgilerini çağrı metninden teyit edin.")
    markdown = "\n".join(md)
    return title, markdown, markdown_to_html(title, markdown)


def markdown_to_html(title, markdown):
    """Tiny renderer for the subset of Markdown build_report emits."""
    def inline(s):
        s = html.escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
        s = re.sub(r"\[(.+?)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', s)
        s = re.sub(r"(?<![\"=>])(https?://[^\s<;]+)", r'<a href="\1">\1</a>', s)
        return s

    out, in_list = [], False
    for line in markdown.splitlines():
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.startswith("### "):
            out.append(f"<h3 style='margin:18px 0 4px;color:#1a3d7c'>{inline(line[4:])}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2 style='border-bottom:2px solid #1a3d7c;padding-bottom:4px'>{inline(line[3:])}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1 style='font-size:20px'>{inline(line[2:])}</h1>")
        elif line.startswith("> "):
            out.append(f"<p style='background:#fff6d6;padding:8px'>{inline(line[2:])}</p>")
        elif line.strip() == "---":
            out.append("<hr>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    body = "\n".join(out)
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title></head>"
            f"<body style='font-family:Arial,sans-serif;max-width:860px;margin:auto;color:#222'>{body}</body></html>")


def send_email(subject, markdown, html_body):
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    to = os.environ.get("REPORT_TO") or user
    if not (user and password and to):
        raise RuntimeError("SMTP_USER / SMTP_PASSWORD / REPORT_TO ortam değişkenleri eksik")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    msg.set_content(markdown)
    msg.add_alternative(html_body, subtype="html")
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or 465)
    with smtplib.SMTP_SSL(host, port, timeout=60) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)


# -------------------------------------------------------------------------- main

def state_path(profile):
    return HERE / profile.get("state_file", "state.json")


def load_state(profile):
    path = state_path(profile)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"seen": {}, "last_run": None}


def save_state(profile, state):
    state_path(profile).write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run(hits, state, now=None, profile=None):
    now = now or datetime.now(timezone.utc)
    profile = profile or load_profile()
    academics = load_academics()
    calls = parse_calls(hits)

    matched = []
    for call in calls:
        m = match_call(call, profile, academics)
        if m["total"] >= MIN_AREA_SCORE and m["title_hit"]:
            matched.append((call, m))
    matched.sort(key=lambda cm: -cm[1]["total"])

    new_matches = [(c, m) for c, m in matched if c["identifier"] not in state["seen"]]
    horizon = (now + timedelta(days=UPCOMING_DAYS)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")
    upcoming = sorted(
        [(c, m) for c, m in matched if c["deadline"] and today <= c["deadline"] <= horizon],
        key=lambda cm: cm[0]["deadline"],
    )

    for c, _ in matched:
        state["seen"].setdefault(c["identifier"], {"first_seen": now.isoformat(), "title": c["title"]})
    state["last_run"] = now.isoformat()

    stats = {"scanned": len(calls), "matched": len(matched)}
    args = (new_matches, matched[:SUMMARY_BEST], upcoming, profile, len(academics), stats)
    return build_report(*args), build_report(*args, summary=True), len(new_matches)


def build_issue_body(summaries):
    """First profile's summary in full, the others in collapsible sections, within the size limit."""
    lead, rest = summaries[0], summaries[1:]
    parts = []
    for title, summary in rest:
        parts.append(f"\n\n<details>\n<summary><b>{html.escape(title)}</b> (açmak için tıklayın)</summary>\n\n"
                     f"{summary}\n\n</details>")
    budget = ISSUE_BODY_LIMIT - len(lead[1]) - 200
    tail = ""
    for part in parts:
        if len(part) <= budget:
            tail += part
            budget -= len(part)
        else:
            tail += "\n\n_Genel rapor bu issue'ya sığmadı; tam rapor repodaki `reports/` klasöründe._"
            break
    return lead[1] + tail


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", action="append", help="yalnızca bu profil(ler)i çalıştır")
    parser.add_argument("--email", action="store_true", help="ilk profilin raporunu SMTP ile e-postala")
    parser.add_argument("--fixture", type=Path, help="API yerine kaydedilmiş JSON yanıtını kullan")
    parser.add_argument("--no-save", action="store_true", help="state dosyalarını güncelleme")
    args = parser.parse_args()

    try:
        if args.fixture:
            hits = json.loads(args.fixture.read_text(encoding="utf-8")).get("results", [])
        else:
            hits = fetch_all_hits()
    except Exception as exc:  # noqa: BLE001 - surface any failure to the user
        print(f"Portal taraması başarısız: {exc}")
        if args.email:
            send_email("AB Fon Taraması BAŞARISIZ", f"Portal taraması başarısız: {exc}",
                       f"<p>Portal taraması başarısız: {html.escape(str(exc))}</p>")
        sys.exit(1)

    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    summaries, first = [], None
    for name in args.profile or PROFILES:
        profile = load_profile(HERE / name)
        prefix = profile.get("file_prefix", "")
        state = load_state(profile)
        (title, markdown, html_body), (_, summary_md, _), new_count = run(hits, state, profile=profile)

        (REPORTS_DIR / f"{prefix}rapor-{stamp}.md").write_text(markdown, encoding="utf-8")
        (REPORTS_DIR / f"{prefix}rapor-{stamp}.html").write_text(html_body, encoding="utf-8")
        (REPORTS_DIR / f"{prefix}ozet-{stamp}.md").write_text(summary_md, encoding="utf-8")
        if not args.no_save:
            save_state(profile, state)
        summaries.append((title, summary_md))
        first = first or (title, markdown, html_body, new_count)
        print(f"{name}: NEW_CALLS_COUNT={new_count}")

    (REPORTS_DIR / f"issue-{stamp}.md").write_text(build_issue_body(summaries), encoding="utf-8")
    print(summaries[0][1])
    if args.email:
        title, markdown, html_body, new_count = first
        send_email(f"{title} — {new_count} yeni çağrı", markdown, html_body)
        print("E-posta gönderildi.")


if __name__ == "__main__":
    main()
