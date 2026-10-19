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
# Per-topic JSON with type of action, type of MGA and the budget table.
TOPIC_DETAILS_URL = "https://ec.europa.eu/info/funding-tenders/opportunities/data/topicDetails/{}.json"
DETAILS_CACHE_PATH = HERE / "topic_cache.json"
DETAILS_CACHE_DAYS = 14  # refetch a topic's details after this many days

# Short action code -> (Turkish label, EU funding rate). Rate depends on the
# type of action, not on the MGA (lump sum vs budget-based).
ACTION_INFO = {
    "RIA": ("Araştırma ve İnovasyon (RIA)", "%100"),
    "IA": ("İnovasyon (IA)", "%70 (kâr amacı gütmeyen kurumlar %100)"),
    "CSA": ("Koordinasyon ve Destek (CSA)", "%100"),
    "JU-RIA": ("JU Araştırma ve İnovasyon", "%100"),
    "JU-IA": ("JU İnovasyon", "%70 (kâr amacı gütmeyen kurumlar %100)"),
    "JU-CSA": ("JU Koordinasyon ve Destek", "%100"),
    "EIC": ("EIC hibesi", "%100"),
    "COFUND": ("Ortak fonlama (COFUND)", "çağrıda belirtilen oran"),
    "PCP": ("Ticari öncesi alım (PCP)", "çağrıda belirtilen oran"),
    "PPI": ("Yenilikçi çözüm alımı (PPI)", "çağrıda belirtilen oran"),
    "MSCA": ("Marie Skłodowska-Curie", "birim maliyet"),
    "ERC": ("ERC", "%100"),
}
MGA_LABELS = {
    "HORIZON-AG-LS": "Lump Sum",
    "HORIZON-AG": "Budget-Based",
    "HORIZON-AG-UN": "Birim maliyet",
}

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
SUMMARY_LUMP_SUM = 15  # lump-sum calls (RIA/CSA first, then IA) in the summary
DRAFT_MIN_DAYS = 30    # partner-search drafts only for calls closing at least this far ahead

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
                # Multi-cut-off topics list several deadlines; run() picks the next one.
                "deadlines": sorted(d[:10] for d in values(meta, "deadlineDate") if d),
                "deadline": None,
                "status": STATUS_LABELS.get(one(meta, "status"), one(meta, "status")),
                "programme": programme_label(programme_id, identifier),
                "url": one(meta, "url") or hit.get("url") or TOPIC_URL.format(identifier.lower()),
                "title_text": title.lower(),
                "body_text": body.lower(),
                # Cascade-funding (FSTP) calls run by EU projects, not regular portal topics.
                "cascade": "competitive-calls-cs" in (one(meta, "url") or hit.get("url") or ""),
                "details": {},
            }
        )
    return calls


# ------------------------------------------------- type of action / type of MGA

def short_action(type_of_action, title=""):
    """'HORIZON-RIA HORIZON Research and ...' -> 'RIA'; falls back to '(RIA)' in the title."""
    if type_of_action:
        code = type_of_action.split()[0].upper()
        for prefix in ("HORIZON-", "DIGITAL-", "EU4H-", "LIFE-"):
            if code.startswith(prefix):
                return code[len(prefix):]
        return code
    m = re.search(r"\((RIA|IA|CSA)\)", title or "")
    return m.group(1) if m else None


def parse_topic_details(identifier, data):
    """Pull type of action, MGA and this topic's budget row out of a topicDetails JSON."""
    td = (data or {}).get("TopicDetails") or data or {}
    out = {"action_full": None, "mga": None, "min": None, "max": None, "grants": None, "budget": None}
    for action in td.get("actions") or []:
        for t in action.get("types") or []:
            out["action_full"] = out["action_full"] or t.get("typeOfAction")
            mgas = t.get("typeOfMGA") or []
            mgas = mgas if isinstance(mgas, list) else [mgas]
            for m in mgas:
                abbr = m.get("abbreviation") if isinstance(m, dict) else m
                out["mga"] = out["mga"] or abbr
    if not out["mga"]:
        for m in td.get("topicMGAs") or []:
            out["mga"] = out["mga"] or (m.get("abbreviation") if isinstance(m, dict) else m)
    rows = ((td.get("budgetOverviewJSONItem") or {}).get("budgetTopicActionMap") or {}).values()
    for row in (r for rs in rows for r in rs):
        if str(row.get("action", "")).upper().startswith(identifier.upper()):
            to_int = lambda v: int(float(v)) if v not in (None, "") else None
            out["min"], out["max"] = to_int(row.get("minContribution")), to_int(row.get("maxContribution"))
            out["grants"] = to_int(row.get("expectedGrants"))
            out["budget"] = sum(to_int(v) or 0 for v in (row.get("budgetYearMap") or {}).values()) or None
            break
    return out


def fetch_topic_details(identifier):
    resp = requests.get(TOPIC_DETAILS_URL.format(identifier.lower()), timeout=30,
                        headers={"Accept": "application/json"})
    resp.raise_for_status()
    return parse_topic_details(identifier, resp.json())


def load_details_cache():
    if DETAILS_CACHE_PATH.exists():
        return json.loads(DETAILS_CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_details_cache(cache):
    DETAILS_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                                  encoding="utf-8")


def enrich_calls(calls, cache, fetcher, now):
    """Attach action / MGA / budget details to each call, using a cache refreshed every DETAILS_CACHE_DAYS."""
    limit = (now - timedelta(days=DETAILS_CACHE_DAYS)).isoformat()
    for call in calls:
        ident = call["identifier"]
        cached = cache.get(ident)
        if fetcher and not call["cascade"] and (not cached or cached.get("fetched", "") < limit):
            try:
                cached = {**fetcher(ident), "fetched": now.isoformat()}
                cache[ident] = cached
            except Exception as exc:  # noqa: BLE001 - one bad topic must not stop the scan
                print(f"Ayrıntı alınamadı: {ident}: {exc}")
        details = dict(cached or {})
        details["action"] = "FSTP" if call["cascade"] else short_action(details.get("action_full"), call["title"])
        call["details"] = details


def priority_group(call):
    """1: lump sum + RIA/CSA, 2: lump sum + IA, 3: everything else."""
    d = call.get("details") or {}
    if d.get("mga") != "HORIZON-AG-LS":
        return 3
    action = (d.get("action") or "").replace("JU-", "")
    if action in ("RIA", "CSA", "EIC"):
        return 1
    return 2 if action == "IA" else 3


def details_text(call):
    d = call.get("details") or {}
    if d.get("action") == "FSTP":
        return "Kaskad fonlama (FSTP) — bir AB projesinin açtığı alt çağrı"
    parts = []
    action = d.get("action")
    if action:
        label, rate = ACTION_INFO.get(action, (action, None))
        parts.append(label + (f" · AB oranı {rate}" if rate else ""))
    if d.get("mga"):
        parts.append(MGA_LABELS.get(d["mga"], d["mga"]))
    if d.get("min") or d.get("max"):
        lo, hi = (d.get("min") or d["max"]) / 1e6, (d.get("max") or d["min"]) / 1e6
        parts.append(f"proje başı {lo:g} M€" if lo == hi else f"proje başı {lo:g}–{hi:g} M€")
    if d.get("grants"):
        parts.append(f"~{d['grants']} proje")
    return " · ".join(parts) or "Aksiyon/MGA bilgisi alınamadı"


def short_tag(call):
    d = call.get("details") or {}
    mga = {"HORIZON-AG-LS": "LS", "HORIZON-AG": "BB"}.get(d.get("mga"), "?")
    return f"{d.get('action') or '?'}·{mga}"


# ---------------------------------------------------------------------- matching

def load_profile(path=PROFILE_PATH):
    """Load a profile; missing ecosystem / Turkey notes are inherited from profile.json."""
    profile = json.loads(Path(path).read_text(encoding="utf-8"))
    if Path(path).resolve() != PROFILE_PATH.resolve():
        base = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        for key in ("ecosystem", "turkey_participation", "exclude_programmes", "action_weights", "mga_weights"):
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

# ------------------------------------------------------- partner-search drafts

# What we offer and whom we look for, by type of action.
DRAFT_ROLES = {
    "RIA": ("research partner leading or contributing to a work package on {areas}, "
            "including method development, experimentation and validation",
            "an experienced coordinator, research organisations and at least one industrial partner"),
    "CSA": ("partner for stakeholder engagement, training, dissemination and market/policy analysis on {areas}",
            "a coordinator and partners with complementary networks across EU Member States"),
    "IA": ("partner for piloting and demonstration on {areas}, bringing industrial end-users "
           "through our regional innovation ecosystem",
           "a coordinator, technology providers and industrial / end-user partners in EU Member States"),
    "EIC": ("research partner contributing breakthrough research on {areas}",
            "a visionary coordinator and high-risk/high-gain research partners"),
}


def select_draft_calls(matched, state, profile, today):
    """Best calls for a partner-search post: lump sum first, enough time left, not drafted before."""
    n = profile.get("partner_search_drafts", 0)
    if not n:
        return []
    cutoff = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=DRAFT_MIN_DAYS)).strftime("%Y-%m-%d")
    drafted = state.setdefault("drafted", {})
    eligible = [(c, m) for c, m in matched
                if not c["cascade"] and (not c["deadline"] or c["deadline"] >= cutoff)]
    fresh = [cm for cm in eligible if cm[0]["identifier"] not in drafted]
    picked = (fresh + [cm for cm in eligible if cm not in fresh])[:n]
    for c, _ in picked:
        drafted.setdefault(c["identifier"], today)
    return picked


def partner_search_draft(call, m, profile):
    """Ready-to-paste English partner-search text plus Turkish guidance for the TTO."""
    action = ((call.get("details") or {}).get("action") or "").replace("JU-", "")
    offer, wanted = DRAFT_ROLES.get(action, DRAFT_ROLES["RIA"])
    by_id = {a["id"]: a for a in profile["focus_areas"]}
    areas = [by_id[a["id"]].get("expertise_en") or a["name"] for a in m["areas"] if a["id"] in by_id]
    areas_txt = "; ".join(areas[:2]) or "the topic's core challenges"
    matched_eco = {e["id"] for e in m["ecosystem"]}
    eco = sorted(profile.get("ecosystem", []), key=lambda e: e["id"] not in matched_eco)
    horizon = (call.get("programme") or "").startswith("Horizon")

    lines = [
        f"{profile.get('institution_en', profile['institution'])} – partner offer for {call['identifier']}",
        "",
        f"Topic: {call['title']}",
        f"Deadline: {call['deadline'] or 'see topic page'}",
        "",
        f"Who we are: {profile.get('institution_en', profile['institution'])} (Istanbul, Türkiye)."
        + (" Türkiye is associated to Horizon Europe, so we participate and receive funding on the same terms"
           " as organisations from EU Member States." if horizon else ""),
        "",
        f"Our expertise: {areas_txt}.",
        "",
        f"Role we offer: {offer.format(areas=areas[0] if areas else areas_txt)}.",
        "",
        "Ecosystem partners who can join the consortium with us (subject to their confirmation):",
    ]
    lines += [f"- {e.get('name_en', e['name'])}: {e.get('role_en', e['role'])}" for e in eco]
    lines += [
        "",
        f"We are looking for: {wanted}.",
        "",
        "Contact: [Ad Soyad, unvan] – [e-posta] – Istanbul Commerce University Technology Transfer Office",
    ]
    tag = short_tag(call)
    eco_tr = ", ".join(e["name"] for e in m["ecosystem"]) or "doğrudan eşleşme yok; üçü de genel destek olarak eklendi"
    out = [
        f"### {call['title']}",
        f"- `{call['identifier']}` · {tag} · son başvuru {call['deadline'] or '-'} · puan {m['total']} · {details_text(call)}",
        f"- Eşleşen ekosistem ortakları: {eco_tr}",
        f"- **Portalda:** [çağrı sayfası]({call['url']}) → *Partner search* sekmesi → ilan oluştur "
        "(EU Login ve kurum PIC numarası gerekir). İTO / BTM / Teknopark adını kullanmadan önce bu kurumlarla teyitleşin.",
        "",
        "```text",
        *lines,
        "```",
        "",
    ]
    return out


def build_report(new_matches, best, upcoming, profile, academics_count, stats, summary=False, all_matches=(),
                 drafts=()):
    """Render the report. summary=True gives the short version used for the GitHub issue."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = f"AB Fon Çağrıları — {profile['institution']} Eşleştirme Raporu ({today})"
    md = [f"# {title}", ""]
    md.append(
        f"Taranan açık/yakında açılacak çağrı: **{stats['scanned']}** "
        f"(süresi geçtiği hâlde portalda açık görünen {stats.get('stale', 0)} çağrı elendi) · "
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
        if m.get("type_weight"):
            weight += f" (aksiyon/MGA ağırlığı {m['type_weight']:+d})"
        out.append(f"- **Son başvuru:** {call['deadline'] or 'Belirtilmemiş'} · **Uygunluk puanı:** {m['total']}{weight}")
        out.append(f"- **Aksiyon / MGA:** {details_text(call)}")
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
        return (f"- **{lead}** — [{call['title']}]({call['url']}) (`{call['identifier']}`, {short_tag(call)}, "
                f"puan {m['total']}, ekosistem: {eco})")

    shown_new = new_matches[:profile.get("summary_new", SUMMARY_NEW)] if summary else new_matches
    md.append(f"## Yeni eşleşen çağrılar ({len(new_matches)})\n")
    if not new_matches:
        md.append("Bu dönemde kurum profiliyle eşleşen yeni bir çağrı bulunamadı.\n")
    for call, m in shown_new:
        md += call_md(call, m)
    if len(new_matches) > len(shown_new):
        md.append(f"_…ve {len(new_matches) - len(shown_new)} yeni çağrı daha: tam rapora bakın._\n")

    if drafts:
        md.append(f"## Ortak arama ilanı taslakları (en uygun {len(drafts)} çağrı)\n")
        md.append("İngilizce metni kopyalayıp portalda ilgili çağrının *Partner search* bölümüne yapıştırın; "
                  "köşeli parantezli alanları doldurun. Daha önce taslağı verilen çağrılar tekrar edilmez.\n")
        for call, m in drafts:
            md += partner_search_draft(call, m, profile)

    groups = [
        (1, "Lump sum + RIA/CSA"),
        (2, "Lump sum + IA"),
        (3, "Diğer (budget-based, COFUND, kaskad veya bilgisi alınamayan)"),
    ]
    if summary:
        lump = [cm for cm in all_matches if priority_group(cm[0]) < 3][:SUMMARY_LUMP_SUM]
        if lump:
            md.append(f"## Lump sum öncelikli çağrılar (ilk {len(lump)}: önce RIA/CSA, sonra IA)\n")
            md.append("Kısaltmalar: LS = Lump Sum, BB = Budget-Based.\n")
            for call, m in lump:
                md.append(line_md(call, m, call["deadline"] or "tarih yok"))
            md.append("")

    if summary and best:
        md.append(f"## En uygun açık çağrılar (ilk {len(best)}, yeni olsun olmasın)\n")
        for call, m in best:
            md.append(line_md(call, m, call["deadline"] or "tarih yok"))
        md.append("")

    if not summary and all_matches:
        md.append(f"## Tüm eşleşen çağrılar ({len(all_matches)})\n")
        for group, label in groups:
            rows = [cm for cm in all_matches if priority_group(cm[0]) == group]
            if rows:
                md.append(f"### {label} ({len(rows)})\n")
                for call, m in rows:
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


def run(hits, state, now=None, profile=None, details_fetcher=None, details_cache=None):
    """Match, enrich and render. details_fetcher(identifier) -> dict, or None to skip portal lookups."""
    now = now or datetime.now(timezone.utc)
    profile = profile or load_profile()
    academics = load_academics()
    today = now.strftime("%Y-%m-%d")
    details_cache = {} if details_cache is None else details_cache

    # The portal keeps some 2023-2024 topics flagged open/forthcoming long after
    # every deadline has passed; drop those and show each call's next deadline.
    # Programmes Turkish organisations cannot join (e.g. EDF: EU/EEA only), by identifier prefix.
    excluded = tuple(p.upper() + "-" for p in profile.get("exclude_programmes", []))
    calls, stale = [], 0
    for call in parse_calls(hits):
        ident = call["identifier"].upper()
        if ident.startswith(excluded) or "CANCELLED" in ident:
            continue
        future = [d for d in call["deadlines"] if d >= today]
        if call["deadlines"] and not future:
            stale += 1
            continue
        call["deadline"] = future[0] if future else None
        calls.append(call)

    matched = []
    for call in calls:
        m = match_call(call, profile, academics)
        if m["total"] >= MIN_AREA_SCORE and m["title_hit"]:
            matched.append((call, m))

    # Type of action / MGA only for matched calls: one small request each, cached.
    enrich_calls([c for c, _ in matched], details_cache, details_fetcher, now)
    action_w, mga_w = profile.get("action_weights", {}), profile.get("mga_weights", {})
    for call, m in matched:
        d = call["details"]
        m["type_weight"] = action_w.get(d.get("action") or "", 0) + mga_w.get(d.get("mga") or "", 0)
        m["total"] += m["type_weight"]
    if profile.get("only_lump_sum"):
        matched = [(c, m) for c, m in matched if priority_group(c) < 3]
    matched.sort(key=lambda cm: (priority_group(cm[0]), -cm[1]["total"]))

    new_matches = [(c, m) for c, m in matched if c["identifier"] not in state["seen"]]
    horizon = (now + timedelta(days=UPCOMING_DAYS)).strftime("%Y-%m-%d")
    upcoming = sorted(
        [(c, m) for c, m in matched if c["deadline"] and today <= c["deadline"] <= horizon],
        key=lambda cm: cm[0]["deadline"],
    )
    best = sorted(matched, key=lambda cm: -cm[1]["total"])[:SUMMARY_BEST]
    drafts = select_draft_calls(matched, state, profile, today)

    for c, _ in matched:
        state["seen"].setdefault(c["identifier"], {"first_seen": now.isoformat(), "title": c["title"]})
    state["last_run"] = now.isoformat()

    stats = {"scanned": len(calls), "matched": len(matched), "stale": stale}
    args = (new_matches, best, upcoming, profile, len(academics), stats)
    return (build_report(*args, all_matches=matched, drafts=drafts),
            build_report(*args, summary=True, all_matches=matched, drafts=drafts), len(new_matches))


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
    parser.add_argument("--no-details", action="store_true",
                        help="aksiyon türü / MGA bilgisini portaldan çekme (hızlı deneme)")
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
    details_cache = load_details_cache()
    fetcher = None if (args.fixture or args.no_details) else fetch_topic_details
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    summaries, first = [], None
    for name in args.profile or PROFILES:
        profile = load_profile(HERE / name)
        prefix = profile.get("file_prefix", "")
        state = load_state(profile)
        (title, markdown, html_body), (_, summary_md, _), new_count = run(hits, state, profile=profile,
                                                                     details_fetcher=fetcher, details_cache=details_cache)

        (REPORTS_DIR / f"{prefix}rapor-{stamp}.md").write_text(markdown, encoding="utf-8")
        (REPORTS_DIR / f"{prefix}rapor-{stamp}.html").write_text(html_body, encoding="utf-8")
        (REPORTS_DIR / f"{prefix}ozet-{stamp}.md").write_text(summary_md, encoding="utf-8")
        if not args.no_save:
            save_state(profile, state)
        summaries.append((title, summary_md))
        first = first or (title, markdown, html_body, new_count)
        print(f"{name}: NEW_CALLS_COUNT={new_count}")

    if not args.no_save:
        save_details_cache(details_cache)
    (REPORTS_DIR / f"issue-{stamp}.md").write_text(build_issue_body(summaries), encoding="utf-8")
    print(summaries[0][1])
    if args.email:
        title, markdown, html_body, new_count = first
        send_email(f"{title} — {new_count} yeni çağrı", markdown, html_body)
        print("E-posta gönderildi.")


if __name__ == "__main__":
    main()
