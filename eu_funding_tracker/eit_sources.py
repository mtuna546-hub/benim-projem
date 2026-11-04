"""EIT / HEI call pages that are not on the EU Funding & Tenders portal.

These sites have no API and each has its own layout, so instead of one parser per site
this collects, from each page in eit_sources.json, the links whose text or address looks
like a call ("call", "open call", "funding", "challenge"...). Links not seen in the
previous run are marked new. A plain-text snapshot of every page is saved under
reports/sources/ so the source list and the filter can be checked and tuned.
"""

import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

HERE = Path(__file__).parent
SOURCES_PATH = HERE / "eit_sources.json"
STATE_PATH = HERE / "state_eit.json"
USER_AGENT = "Mozilla/5.0 (compatible; eu-funding-tracker/1.0)"
CALL_WORDS = re.compile(r"\b(open )?calls?\b|call for|funding|grant|challenge|programme|accelerat|"
                        r"apply|application|tender|opportunit|booster|scale-?up", re.I)
SKIP_WORDS = re.compile(r"privacy|cookie|login|sign in|newsletter|linkedin|twitter|facebook|youtube|"
                        r"instagram|contact us|terms|imprint|accessibility", re.I)
MAX_LINKS = 12


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.text, self._href, self._buf = [], [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._buf = dict(attrs).get("href"), []

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join("".join(self._buf).split())))
            self._href = None

    def handle_data(self, data):
        self.text.append(data)
        if self._href is not None:
            self._buf.append(data)


def call_links(page_html, base_url):
    """(title, absolute url) pairs that look like calls, same site only, de-duplicated."""
    parser = _Links()
    parser.feed(page_html)
    host = urlparse(base_url).netloc.replace("www.", "")
    out, seen = [], set()
    for href, text in parser.links:
        url = urljoin(base_url, html.unescape(href or "")).split("#")[0]
        if not url.startswith("http") or host not in urlparse(url).netloc or url.rstrip("/") == base_url.rstrip("/"):
            continue
        if len(text) < 12 or SKIP_WORDS.search(text) or not (CALL_WORDS.search(text) or CALL_WORDS.search(url)):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append((text[:160], url))
    return out, " ".join(" ".join(parser.text).split())


def collect(fetch=None, snapshot_dir=None):
    """Return a list of per-source results; fetch(url) -> (status, final_url, html) for tests."""
    fetch = fetch or _fetch
    sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))["sources"]
    state = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}
    results = []
    for src in sources:
        res = {"id": src["id"], "name": src["name"], "url": src["url"], "links": [], "error": None}
        try:
            status, final_url, body = fetch(src["url"])
            if status >= 400:
                res["error"] = f"HTTP {status}"
            else:
                links, text = call_links(body, final_url)
                known = set(state.get(src["id"], []))
                res["links"] = [{"title": t, "url": u, "new": bool(known) and u not in known} for t, u in links]
                state[src["id"]] = sorted(known | {u for _, u in links})
                if snapshot_dir:
                    snapshot_dir.mkdir(parents=True, exist_ok=True)
                    (snapshot_dir / f"{src['id']}.txt").write_text(
                        f"URL: {final_url}\nHTTP {status}\n\n" + "\n".join(f"{t} | {u}" for t, u in links)
                        + "\n\n---\n" + text[:20000], encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - one site must never stop the scan
            res["error"] = str(exc)[:120]
        print(f"EIT kaynağı {src['id']}: {res['error'] or str(len(res['links'])) + ' bağlantı'}")
        results.append(res)
    return results, state


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _fetch(url):
    resp = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
    return resp.status_code, resp.url, resp.text


def section_md(results):
    md = ["## EIT ve HEI çağrıları (portal dışı kaynaklar)\n",
          "Bu çağrılar EU Funding & Tenders portalında yayımlanmaz; her hafta kurumların kendi sitelerinden "
          "toplanır. 🆕 = geçen haftadan bu yana sitede yeni görünen bağlantı. Başvuru koşullarını sitesinden "
          "teyit edin.\n"]
    for res in results:
        head = f"**{res['name']}** · [sayfa]({res['url']})"
        if res["error"]:
            md.append(f"- {head} · ⚠️ okunamadı ({res['error']})")
            continue
        if not res["links"]:
            md.append(f"- {head} · çağrı bağlantısı bulunamadı")
            continue
        links = sorted(res["links"], key=lambda l: not l["new"])[:MAX_LINKS]
        md.append(f"- {head}")
        md += [f"  - {'🆕 ' if l['new'] else ''}[{l['title']}]({l['url']})" for l in links]
    md.append("")
    return "\n".join(md)
