#!/usr/bin/env python3
"""Snapshot NCCD textbook pages so the catalog can be built from them.

Fetches every candidate grade page (TextBooksGrade/<id>), then one level of
internal pages linked from them, saving raw HTML plus a links.json summary of
every link seen (and which ones point at PDFs).
"""
import json, re, sys, time, pathlib, hashlib
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

BASE = "https://www.nccd.gov.jo"
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "crawl")
RAW = OUT / "raw"
RAW.mkdir(parents=True, exist_ok=True)
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
S.headers["Accept-Language"] = "ar,en;q=0.8"

def fname(url):
    p = urlparse(url)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", p.path + ("_" + p.query if p.query else "")).strip("_")[:120]
    return f"{slug or 'root'}_{hashlib.md5(url.encode()).hexdigest()[:6]}.html"

def get(url):
    for attempt in range(3):
        try:
            r = S.get(url, timeout=60)
            return r
        except Exception as e:
            print(f"  ! {url}: {e}", flush=True)
            time.sleep(3 * (attempt + 1))
    return None

pages, log = {}, []
def fetch_page(url, kind):
    if url in pages:
        return pages[url]
    r = get(url)
    time.sleep(0.4)
    entry = {"url": url, "kind": kind, "status": r.status_code if r is not None else None,
             "final_url": r.url if r is not None else None,
             "ctype": r.headers.get("content-type") if r is not None else None}
    links = []
    if r is not None and r.ok and "html" in (r.headers.get("content-type") or ""):
        r.encoding = r.apparent_encoding if not r.encoding or r.encoding.lower() == "iso-8859-1" else r.encoding
        html = r.text
        f = fname(url)
        (RAW / f).write_text(html, encoding="utf-8")
        entry["file"] = f
        soup = BeautifulSoup(html, "html.parser")
        entry["title"] = (soup.title.string or "").strip() if soup.title else ""
        for a in soup.find_all("a", href=True):
            href = urljoin(r.url, a["href"].strip())
            links.append({"href": href, "text": " ".join(a.get_text(" ").split())[:200]})
        for tag in soup.find_all(["iframe", "embed", "object"]):
            src = tag.get("src") or tag.get("data")
            if src:
                links.append({"href": urljoin(r.url, src), "text": f"<{tag.name}>"})
    entry["links"] = links
    pages[url] = entry
    print(f"[{entry['status']}] {kind:6} {url} -> {len(links)} links  {entry.get('title','')[:60]}", flush=True)
    return entry

def is_pdf(h):
    return ".pdf" in h.lower()

# 1) grade pages
grade_urls = [f"{BASE}/ar/pages/TextBooksGrade/{i}" for i in range(55, 100)]
for u in grade_urls:
    fetch_page(u, "grade")

# 2) one level of internal non-PDF links from grade pages
seen_internal = set()
for u in grade_urls:
    for l in pages[u]["links"]:
        h = l["href"].split("#")[0]
        p = urlparse(h)
        if p.netloc.endswith("nccd.gov.jo") and not is_pdf(h) and h not in pages:
            seen_internal.add(h)

# Skip obvious site chrome (same link present on nearly every grade page)
from collections import Counter
cnt = Counter()
ok_grades = [u for u in grade_urls if pages[u]["status"] == 200]
for u in ok_grades:
    for h in {l["href"].split("#")[0] for l in pages[u]["links"]}:
        cnt[h] += 1
chrome = {h for h, c in cnt.items() if len(ok_grades) > 3 and c >= max(3, len(ok_grades) * 0.6)}
level2 = sorted(h for h in seen_internal if h not in chrome)
print(f"\n{len(ok_grades)} grade pages OK, {len(chrome)} chrome links skipped, {len(level2)} level-2 pages", flush=True)
for h in level2[:800]:
    fetch_page(h, "sub")

pdfs = sorted({l["href"] for e in pages.values() for l in e["links"] if is_pdf(l["href"])})
(OUT / "links.json").write_text(json.dumps({"pages": list(pages.values()), "chrome": sorted(chrome)},
                                           ensure_ascii=False, indent=1), encoding="utf-8")
(OUT / "pdf_links.txt").write_text("\n".join(pdfs) + "\n", encoding="utf-8")
print(f"\nDone: {len(pages)} pages, {len(pdfs)} distinct PDF links", flush=True)
