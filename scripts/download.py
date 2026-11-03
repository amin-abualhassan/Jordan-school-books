#!/usr/bin/env python3
"""Download and verify the books listed in catalog/manifest.csv.

Source order for each book:
  1. the official file on nccd.gov.jo (skipped automatically when the site is
     unreachable, which it is from outside Jordan)
  2. Internet Archive captures of that exact official file, newest first
  3. extra sources listed in catalog/fallbacks.csv (unofficial mirrors), if any

A file is accepted only if it is a complete PDF: starts with %PDF, ends with
%%EOF, matches the original Content-Length when the archive records one, and
pdfinfo can read it. Truncated or broken captures are rejected and the next
candidate is tried.

Usage: download.py <grade_key|all> <out_dir>
Writes <out_dir>/files/<n>.pdf and <out_dir>/results.json
"""
import csv, hashlib, json, os, pathlib, re, subprocess, sys, time
from collections import defaultdict
from urllib.parse import unquote, urlsplit
import requests

CAT = pathlib.Path("catalog")
grade_arg, OUT = sys.argv[1], pathlib.Path(sys.argv[2])
(OUT / "files").mkdir(parents=True, exist_ok=True)

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) jordan-school-books/1.0 (personal archive)"
WAYBACK_GAP = 4.0  # seconds between Internet Archive requests
_last = [0.0]


def norm_path(u):
    p = unquote(urlsplit(u).path if "://" in u else u)
    return " ".join(p.lower().split())


def wait_turn():
    d = time.time() - _last[0]
    if d < WAYBACK_GAP:
        time.sleep(WAYBACK_GAP - d)
    _last[0] = time.time()


def fetch(url, dest, wayback=False, tries=4, timeout=300):
    """Stream url to dest. Returns (ok, info)."""
    err = ""
    for i in range(tries):
        if wayback:
            wait_turn()
        try:
            with S.get(url, stream=True, timeout=(30, timeout), allow_redirects=True) as r:
                if r.status_code in (429, 503) or r.status_code >= 500:
                    err = f"HTTP {r.status_code}"
                    time.sleep(30 * (i + 1))
                    continue
                if r.status_code != 200:
                    return False, {"error": f"HTTP {r.status_code}", "final_url": r.url}
                expected = r.headers.get("x-archive-orig-content-length") or (
                    None if wayback else r.headers.get("content-length"))
                with open(dest, "wb") as fh:
                    for chunk in r.iter_content(1 << 20):
                        fh.write(chunk)
                return True, {"final_url": r.url, "expected_size": int(expected) if expected and expected.isdigit() else None}
        except Exception as e:
            err = f"{e.__class__.__name__}: {str(e)[:150]}"
            time.sleep(20 * (i + 1))
    return False, {"error": err or "failed"}


def verify(path, expected_size=None):
    size = path.stat().st_size
    with open(path, "rb") as fh:
        head = fh.read(1024)
        fh.seek(max(0, size - 2048))
        tail = fh.read()
    if b"%PDF" not in head:
        return False, "not a PDF", {}
    if b"%%EOF" not in tail:
        return False, f"truncated (no %%EOF at end, {size} bytes)", {}
    if expected_size and expected_size != size:
        return False, f"size {size} != original {expected_size}", {}
    p = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True)
    m = re.search(r"^Pages:\s+(\d+)", p.stdout, re.M)
    if p.returncode != 0 or not m or int(m.group(1)) == 0:
        return False, "pdfinfo failed: " + (p.stderr.strip()[:150] or "no pages"), {}
    return True, "ok", {"pages": int(m.group(1)), "size": size}


def official_reachable():
    try:
        S.get("https://www.nccd.gov.jo/", timeout=20)
        return True
    except Exception:
        return False


# ---- load inputs
rows = list(csv.DictReader(open(CAT / "manifest.csv", encoding="utf-8")))
if grade_arg != "all":
    rows = [r for r in rows if r["grade_key"] == grade_arg]

captures = defaultdict(list)  # norm path -> [(timestamp, original)]
cdx = CAT / "cdx_root_storage.txt"
if cdx.exists():
    for line in cdx.read_text(encoding="utf-8").splitlines():
        parts = line.split(" ")
        if len(parts) >= 3 and parts[2] == "200":
            captures[norm_path(parts[1])].append((parts[0], parts[1]))
for v in captures.values():
    v.sort(reverse=True)

fallbacks = defaultdict(list)  # manifest card key -> [url]
fb = CAT / "fallbacks.csv"
if fb.exists():
    for r in csv.DictReader(open(fb, encoding="utf-8")):
        fallbacks[(r["grade_key"], r["path"] or r["key"])].append(r["url"])

OFFICIAL = official_reachable()
print(f"official site reachable: {OFFICIAL}; {len(rows)} books; {len(captures)} archived paths", flush=True)

results = []
for n, r in enumerate(rows):
    key = r["path"] or f"G{r['grade_key']}|{r['subject_ar']}|S{r['semester']}|{r['type']}"
    dest = OUT / "files" / f"{n:04d}.pdf"
    tmp = dest.with_suffix(".part")
    cands = []
    if r["path"]:
        if OFFICIAL:
            cands.append(("official", r["official_url"], False))
        caps = captures.get(norm_path(r["path"]), [])
        for ts, orig in caps[:6]:
            cands.append((f"wayback:{ts}", f"https://web.archive.org/web/{ts}id_/{orig}", True))
        if not caps:
            cands.append(("wayback:nearest", f"https://web.archive.org/web/2026id_/{r['official_url']}", True))
    for u in fallbacks.get((r["grade_key"], key), []):
        cands.append(("mirror", u, False))

    rec = dict(r, n=n, status="missing", source="", source_url="", attempts=[])
    for label, url, wb in cands:
        ok, info = fetch(url, tmp, wayback=wb)
        if not ok:
            rec["attempts"].append(f"{label}: {info.get('error')}")
            continue
        good, why, meta = verify(tmp, info.get("expected_size"))
        if not good:
            rec["attempts"].append(f"{label}: {why}")
            continue
        tmp.rename(dest)
        h = hashlib.sha256(dest.read_bytes()).hexdigest()
        rec.update(status="ok", source=label, source_url=info.get("final_url", url), file=dest.name, sha256=h, **meta)
        break
    if tmp.exists():
        tmp.unlink()
    if not cands:
        rec["attempts"].append("no link on NCCD and no fallback source")
    results.append(rec)
    print(f"[{n+1}/{len(rows)}] {rec['status']:7} G{r['grade_key']} {r['subject_en'] or r['subject_ar']} S{r['semester']} {r['type']}"
          f" <- {rec['source'] or '; '.join(rec['attempts'])[:200]}", flush=True)

json.dump(results, open(OUT / "results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
ok = sum(1 for x in results if x["status"] == "ok")
print(f"\n{ok}/{len(results)} books downloaded and verified", flush=True)
