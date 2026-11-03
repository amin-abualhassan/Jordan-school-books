#!/usr/bin/env python3
"""Fetch the official NCCD textbook catalog from the Internet Archive.

nccd.gov.jo is not reachable from outside Jordan, so this pulls:
  1. the most recent archived copy of each grade page (TextBooksGrade/<id>)
  2. the Wayback CDX index of every archived file under /EBV4.0/Root_Storage/
Requests are spaced out to stay within the Archive's rate limits.
"""
import sys, time, pathlib, requests

OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "catalog")
SNAP = OUT / "snapshots"
SNAP.mkdir(parents=True, exist_ok=True)
GRADES = [68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 117, 83]
S = requests.Session()
S.headers["User-Agent"] = "jordan-school-books/1.0 (personal archive; polite)"

def get(url, ok=lambda r: r.status_code == 200, tries=6):
    for i in range(tries):
        try:
            r = S.get(url, timeout=180)
            if ok(r):
                return r
            print(f"  {r.status_code} {url}", flush=True)
        except Exception as e:
            print(f"  ! {e.__class__.__name__} {url}", flush=True)
        time.sleep(20 * (i + 1))
    return None

import json, re
stamps = {}
for g in GRADES:
    # 99991231235959 = "closest to the far future", i.e. the newest capture
    url = f"https://web.archive.org/web/99991231235959id_/https://nccd.gov.jo/ar/pages/TextBooksGrade/{g}"
    r = get(url, ok=lambda r: r.status_code == 200 and "lvComponent14Book" in r.text)
    if r is None:
        print(f"FAILED grade {g}", flush=True)
    else:
        (SNAP / f"grade_{g}.html").write_text(r.text, encoding="utf-8")
        m = re.search(r"/web/(\d{14})", r.url)
        stamps[g] = {"capture": m.group(1) if m else None, "url": r.url}
        print(f"grade {g}: {len(r.text)} chars from {r.url}", flush=True)
    time.sleep(6)
(SNAP / "captures.json").write_text(json.dumps(stamps, indent=1), encoding="utf-8")

# All captures of the grade pages, to see how fresh the newest one is
time.sleep(6)
r = get("https://web.archive.org/cdx/search/cdx?url=nccd.gov.jo/ar/pages/TextBooksGrade/&matchType=prefix"
        "&fl=timestamp,original,statuscode&filter=statuscode:200&output=txt")
if r is not None:
    (OUT / "cdx_grade_pages.txt").write_text(r.text, encoding="utf-8")

# CDX index of all archived files under Root_Storage (paged)
rows, page = [], 0
base = ("https://web.archive.org/cdx/search/cdx?url=nccd.gov.jo/EBV4.0/Root_Storage/"
        "&matchType=prefix&fl=timestamp,original,statuscode,mimetype,length,digest&output=txt")
npages = get(base + "&showNumPages=true")
n = int(npages.text.strip()) if npages is not None and npages.text.strip().isdigit() else 1
print(f"CDX pages: {n}", flush=True)
for page in range(n):
    time.sleep(6)
    r = get(base + f"&page={page}")
    if r is None:
        print(f"FAILED cdx page {page}", flush=True)
        continue
    rows.extend(l for l in r.text.splitlines() if l.strip())
    print(f"cdx page {page}: total rows {len(rows)}", flush=True)
(OUT / "cdx_root_storage.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
print(f"Done: {len(rows)} CDX rows", flush=True)
