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
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml",
           "Accept-Language": "en-GB,en;q=0.9"}
# Strong words: a link whose text has one of these is taken anywhere on the page. Other links are
# taken only if they sit under the page's own path (e.g. /opportunities/<call>), which drops menus.
CALL_WORDS = re.compile(r"\b(open )?calls?\b|call for|funding|grant|tender|booster|prize|award|"
                        r"competition|apply|application|accelerat", re.I)
SKIP_WORDS = re.compile(r"privacy|cookie|login|sign in|newsletter|linkedin|twitter|facebook|youtube|"
                        r"instagram|contact us|terms|imprint|accessibility", re.I)
MAX_LINKS = 12
NOT_HTML = re.compile(r"\.(png|jpe?g|gif|svg|webp|pdf|zip)$", re.I)


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
    base_path = urlparse(base_url).path.rstrip("/")
    out, seen = [], set()
    for href, text in parser.links:
        url = urljoin(base_url, html.unescape(href or "")).split("#")[0]
        if not url.startswith("http") or host not in urlparse(url).netloc or url.rstrip("/") == base_url.rstrip("/"):
            continue
        child = bool(base_path) and urlparse(url).path.rstrip("/").startswith(base_path + "/")
        if len(text) < 12 or SKIP_WORDS.search(text) or not (CALL_WORDS.search(text) or child):
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
        urls = src.get("urls") or [src["url"]]
        res = {"id": src["id"], "name": src["name"], "url": urls[0], "links": [], "error": None}
        errors = []
        for url in urls:
            try:
                status, final_url, body = fetch(url)
            except Exception as exc:  # noqa: BLE001 - one site must never stop the scan
                errors.append(str(exc)[:80])
                continue
            if status >= 400:
                errors.append(f"HTTP {status}")
                continue
            if NOT_HTML.search(urlparse(final_url).path) or "<a" not in body[:500000].lower():
                errors.append("sayfa değil")
                continue
            links, text = call_links(body, final_url)
            res["url"] = url
            known = set(state.get(src["id"], []))
            res["links"] = [{"title": t, "url": u, "new": bool(known) and u not in known} for t, u in links]
            state[src["id"]] = sorted(known | {u for _, u in links})
            if snapshot_dir:
                snapshot_dir.mkdir(parents=True, exist_ok=True)
                (snapshot_dir / f"{src['id']}.txt").write_text(
                    f"URL: {final_url}\nHTTP {status}\n\n" + "\n".join(f"{t} | {u}" for t, u in links)
                    + "\n\n---\n" + text[:20000], encoding="utf-8")
            if links:
                break
        if not res["links"] and errors and len(errors) == len(urls):
            res["error"] = " / ".join(dict.fromkeys(errors))
        print(f"EIT kaynağı {src['id']}: {res['error'] or str(len(res['links'])) + ' bağlantı'}")
        results.append(res)
    return results, state


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _fetch(url):
    resp = requests.get(url, timeout=30, headers=HEADERS)
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


if __name__ == "__main__":
    # Diagnostic run (CI on pull requests): print what each source yields, save nothing.
    import sys
    out, _ = collect()
    print(section_md(out))
    sys.exit(0)
