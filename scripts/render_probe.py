#!/usr/bin/env python3
"""Render a few pages in a real browser and record network requests,
in case the textbook lists are loaded by JavaScript."""
import json, sys, pathlib
from playwright.sync_api import sync_playwright

OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "crawl") / "rendered"
OUT.mkdir(parents=True, exist_ok=True)
urls = sys.argv[2:] or ["https://www.nccd.gov.jo/ar/pages/TextBooksGrade/68"]
with sync_playwright() as p:
    b = p.chromium.launch()
    for i, u in enumerate(urls):
        pg = b.new_page()
        reqs = []
        pg.on("request", lambda r: reqs.append({"url": r.url, "type": r.resource_type, "method": r.method}))
        try:
            pg.goto(u, wait_until="networkidle", timeout=90000)
            pg.wait_for_timeout(3000)
        except Exception as e:
            print("render error", u, e)
        (OUT / f"page{i}.html").write_text(pg.content(), encoding="utf-8")
        (OUT / f"page{i}_requests.json").write_text(json.dumps({"url": u, "requests": reqs}, indent=1), encoding="utf-8")
        print(u, len(reqs), "requests")
        pg.close()
    b.close()
