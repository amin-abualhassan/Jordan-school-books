#!/usr/bin/env python3
"""Open every link in SAMPLES.md and report whether it returns a PDF."""
import re, sys, time, requests
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0"
ok = True
for url in re.findall(r"\]\((https://[^()\s]+(?:\([^()\s]*\)[^()\s]*)*)\)", open("SAMPLES.md", encoding="utf-8").read()):
    try:
        for attempt in range(5):  # the Internet Archive answers 429 to rapid requests; wait and retry
            r = S.get(url, timeout=120)
            if r.status_code != 429:
                break
            time.sleep(20 * (attempt + 1))
        time.sleep(8)
        kind = "PDF" if r.content[:5] == b"%PDF-" else r.headers.get("content-type", "?")
        print(f"{r.status_code} {kind:24} {len(r.content):>10} bytes  {url[:110]}")
    except Exception as e:
        ok = False
        print("ERR", e, url[:110])
sys.exit(0 if ok else 1)
