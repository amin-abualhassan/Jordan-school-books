#!/usr/bin/env python3
"""Open every link in SAMPLES.md and report whether it returns a PDF."""
import re, sys, requests
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0"
ok = True
for url in re.findall(r"\]\((https://[^)\s]+(?:\([^)]*\)[^)\s]*)*)\)", open("SAMPLES.md", encoding="utf-8").read()):
    try:
        r = S.get(url, timeout=120)
        kind = "PDF" if r.content[:5] == b"%PDF-" else r.headers.get("content-type", "?")
        print(f"{r.status_code} {kind:24} {len(r.content):>10} bytes  {url[:110]}")
    except Exception as e:
        ok = False
        print("ERR", e, url[:110])
sys.exit(0 if ok else 1)
