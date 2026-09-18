#!/usr/bin/env python3
"""Daily tracker for the EU Funding & Tenders Portal (SEDIA search API).

Queries the portal for currently OPEN calls for proposals (grant topics)
matching KEYWORDS below, compares them against state.json (calls already
seen on a previous run), and prints a Turkish markdown summary of anything
new. Run daily; state.json is meant to be committed so the "new since
yesterday" diff survives across runs.

Edit KEYWORDS to change what gets tracked.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ENDPOINT = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
API_KEY = "SEDIA"
STATE_PATH = Path(__file__).parent / "state.json"

TYPE_GRANTS = "1"
STATUS_OPEN = "31094502"
PAGE_SIZE = 50

# Dijitalleşme / Yapay Zeka / Teknoloji odaklı arama terimleri.
KEYWORDS = [
    "artificial intelligence",
    "digital transformation",
    "digitalisation",
    "digital technology",
    "cybersecurity",
    "data economy",
]

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


def search(text, page_size=PAGE_SIZE, page_number=1):
    params = {
        "apiKey": API_KEY,
        "text": text,
        "pageSize": str(page_size),
        "pageNumber": str(page_number),
    }
    query = {
        "bool": {
            "must": [
                {"terms": {"type": [TYPE_GRANTS]}},
                {"terms": {"status": [STATUS_OPEN]}},
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
    resp = requests.post(
        ENDPOINT, params=params, files=files, headers={"Accept": "application/json"}, timeout=30
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("type") == "throwable":
        raise RuntimeError(f"SEDIA API error: {data.get('message')}")
    return data


def one(meta, key):
    """Every metadata value the API returns is wrapped in a single-element list."""
    v = meta.get(key) if meta else None
    if isinstance(v, list):
        return str(v[0]) if v else None
    return str(v) if v is not None else None


def collect_open_calls():
    rows = []
    seen_ids = set()
    for kw in KEYWORDS:
        data = search(kw)
        for hit in data.get("results", []):
            meta = hit.get("metadata") or {}
            identifier = one(meta, "identifier")
            if not identifier or identifier in seen_ids:
                continue
            seen_ids.add(identifier)
            programme_id = one(meta, "frameworkProgramme")
            rows.append(
                {
                    "identifier": identifier,
                    "title": one(meta, "title"),
                    "deadline": one(meta, "deadlineDate"),
                    "programme": PROGRAMME_LABELS.get(programme_id, programme_id),
                    "url": one(meta, "url"),
                    "matched_keyword": kw,
                }
            )
    return rows


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"seen": {}, "last_run": None}


def save_state(state):
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def format_summary(new_calls, error=None):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"# AB Fonları Günlük Özet — {today}", ""]
    if error:
        lines.append(f"Kontrol başarısız oldu: {error}")
        return "\n".join(lines)
    if not new_calls:
        lines.append("Bugün takip edilen anahtar kelimelerle yeni bir açık çağrı bulunamadı.")
        return "\n".join(lines)
    lines.append(f"Bugün {len(new_calls)} yeni açık çağrı bulundu:\n")
    for c in new_calls:
        lines.append(f"## {c['title']}")
        lines.append(f"- Tanımlayıcı: `{c['identifier']}`")
        lines.append(f"- Program: {c['programme'] or 'Belirtilmemiş'}")
        lines.append(f"- Son başvuru tarihi: {c['deadline'] or 'Belirtilmemiş'}")
        lines.append(f"- Eşleşen anahtar kelime: {c['matched_keyword']}")
        if c["url"]:
            lines.append(f"- Bağlantı: {c['url']}")
        lines.append("")
    return "\n".join(lines)


def main():
    state = load_state()
    try:
        calls = collect_open_calls()
    except Exception as exc:  # noqa: BLE001 - surface any failure in the summary
        print(format_summary([], error=str(exc)))
        sys.exit(1)

    new_calls = [c for c in calls if c["identifier"] not in state["seen"]]

    now = datetime.now(timezone.utc).isoformat()
    for c in calls:
        state["seen"].setdefault(c["identifier"], {"first_seen": now, "title": c["title"]})
    state["last_run"] = now
    save_state(state)

    print(format_summary(new_calls))
    print(f"\n---\nNEW_CALLS_COUNT={len(new_calls)}")


if __name__ == "__main__":
    main()
