#!/usr/bin/env python3
"""Query the Internet Archive's live CDX index for recent NCCD material.

Writes catalog/cdx_2026_2027.txt  (files under /EBV4.0/Root_Storage/AR/2026-2027 book/)
       catalog/cdx_pages_recent.txt (any nccd.gov.jo page captured since July 2026)
"""
import time, pathlib, requests

S = requests.Session()
S.headers["User-Agent"] = "jordan-school-books/1.0 (personal archive; polite)"
OUT = pathlib.Path("catalog")
QUERIES = {
    "cdx_2026_2027.txt": "url=nccd.gov.jo/EBV4.0/Root_Storage/AR/2026-2027&matchType=prefix"
                         "&fl=timestamp,original,statuscode,mimetype,length,digest",
    "cdx_pages_recent.txt": "url=nccd.gov.jo/ar/&matchType=prefix&from=20260701"
                            "&fl=timestamp,original,statuscode&filter=statuscode:200&collapse=urlkey",
}
from urllib.parse import quote
dirs = OUT / "probe_dirs.txt"
if dirs.exists():
    QUERIES = {}
    for i, d in enumerate(l.strip() for l in dirs.read_text(encoding="utf-8").splitlines() if l.strip()):
        QUERIES[f"probe/dir_{i}.txt"] = ("url=" + quote("nccd.gov.jo" + d + "/", safe="") + "&matchType=prefix"
                                         "&fl=timestamp,original,statuscode,mimetype,length,digest")
    (OUT / "probe").mkdir(exist_ok=True)
for name, q in QUERIES.items():
    for i in range(5):
        try:
            r = S.get("https://web.archive.org/cdx/search/cdx?" + q + "&output=txt", timeout=300)
            if r.status_code == 200:
                (OUT / name).write_text(r.text, encoding="utf-8")
                print(name, len(r.text.splitlines()), "rows", flush=True)
                break
            print(name, "HTTP", r.status_code, flush=True)
        except Exception as e:
            print(name, "!", e, flush=True)
        time.sleep(30 * (i + 1))
    time.sleep(8)
