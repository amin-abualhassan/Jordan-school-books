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
S.headers["Referer"] = "https://www.minhaji.net/"
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


_digest_seen = set()


def capture_list(official_url):
    """All 200-status captures of one URL, newest first, one per distinct content digest."""
    q = ("https://web.archive.org/cdx/search/cdx?url=" + requests.utils.quote(official_url, safe="")
         + "&fl=timestamp,original,statuscode,digest&filter=statuscode:200&output=txt")
    for i in range(3):
        wait_turn()
        try:
            r = S.get(q, timeout=120)
            if r.status_code == 200:
                rows, seen = [], set()
                for line in r.text.splitlines():
                    p = line.split(" ")
                    if len(p) >= 4 and p[3] not in seen:
                        seen.add(p[3])
                        rows.append((p[0], p[1]))
                # keep newest capture of each digest, newest first
                return sorted(rows, reverse=True)
        except Exception:
            pass
        time.sleep(20 * (i + 1))
    return []


def prefix_matches(url, prefix):
    """Stream only as many bytes as the partial official copy has, and compare."""
    ref = prefix.read_bytes()
    try:
        with S.get(url, stream=True, timeout=(30, 120)) as r:
            if r.status_code != 200:
                return False
            got = bytearray()
            for chunk in r.iter_content(1 << 20):
                got += chunk
                if len(got) >= len(ref) or got[:len(got)] != ref[:len(got)]:
                    break
            return bytes(got[:len(ref)]) == ref
    except Exception:
        return False


def official_reachable():
    try:
        S.get("https://www.nccd.gov.jo/", timeout=20)
        return True
    except Exception:
        return False


# ---- load inputs
rows = list(csv.DictReader(open(os.environ.get("MANIFEST", CAT / "manifest.csv"), encoding="utf-8")))
if grade_arg != "all":
    rows = [r for r in rows if r["grade_key"] == grade_arg]

fallbacks = defaultdict(list)  # manifest card key -> [url]
fb = CAT / "fallbacks.csv"
if fb.exists():
    for r in csv.DictReader(open(fb, encoding="utf-8")):
        fallbacks[(r["grade_key"], r["path"] or r["key"])].append(
            (r["url"], r.get("mirror", "mirror"), r.get("match", "strict")))

OFFICIAL = official_reachable()
print(f"official site reachable: {OFFICIAL}; {len(rows)} books", flush=True)

results = []
for n, r in enumerate(rows):
    key = r["path"] or f"G{r['grade_key']}|{r['subject_ar']}|S{r['semester']}|{r['type']}"
    dest = OUT / "files" / f"{n:04d}.pdf"
    tmp = dest.with_suffix(".part")
    cands = []
    if r["path"]:
        if OFFICIAL:
            cands.append(("official", r["official_url"], False))
        if os.environ.get("NO_WAYBACK"):
            pass
        else:
            cands.append(("wayback:latest", f"https://web.archive.org/web/99991231235959id_/{r['official_url']}", True))
            cands.append(("wayback:others", r["official_url"], True))  # expanded lazily below
    fb = fallbacks.get((r["grade_key"], key), [])
    # strict matches first; loose ones (other semester/type label) only count if byte-identical to official
    for u, mname, kind in sorted(fb, key=lambda x: x[2] != "strict"):
        cands.append((f"mirror:{mname}" + (":loose" if kind == "loose" else ""), u, False))
    for alt in filter(None, (r.get("alt_urls") or "").split(" | ")) if not os.environ.get("NO_WAYBACK") else []:
        cands.append(("older-edition:latest", f"https://web.archive.org/web/99991231235959id_/{alt}", True))

    rec = dict(r, n=n, status="missing", source="", source_url="", attempts=[], official_match="")
    prefix = OUT / "files" / f"{n:04d}.prefix"
    backup, backup_meta = OUT / "files" / f"{n:04d}.backup", {}
    tried_ts = set()
    queue = list(cands)
    while queue:
        label, url, wb = queue.pop(0)
        if label == "wayback:others":
            # Only reached when the newest capture failed: list every capture of this exact file
            more = []
            for ts, orig in capture_list(url):
                if ts not in tried_ts:
                    more.append((f"wayback:{ts}", f"https://web.archive.org/web/{ts}id_/{orig}", True))
            queue[0:0] = more[:5]
            if not more:
                rec["attempts"].append("wayback: no other captures")
            continue
        if label.endswith(":loose"):
            if not prefix.exists():
                continue  # cannot prove identity without a partial official copy
            if not prefix_matches(url, prefix):
                rec["attempts"].append(f"{label}: not the same file as the official one")
                continue
        ok, info = fetch(url, tmp, wayback=wb)
        m = re.search(r"/web/(\d{14})", info.get("final_url", "") or "")
        if wb and m:
            tried_ts.add(m.group(1))
            label = f"{label.split(':')[0]}:{m.group(1)}"
        if not ok:
            rec["attempts"].append(f"{label}: {info.get('error')}")
            continue
        good, why, meta = verify(tmp, info.get("expected_size"))
        if not good:
            rec["attempts"].append(f"{label}: {why}")
            if wb and why.startswith("truncated") and tmp.stat().st_size > (prefix.stat().st_size if prefix.exists() else 0):
                tmp.replace(prefix)  # partial official file: used below to check mirror copies
            continue
        if label.startswith("mirror"):
            if prefix.exists():
                ref = prefix.read_bytes()
                with open(tmp, "rb") as fh:
                    same = fh.read(len(ref)) == ref
                rec["official_match"] = (f"identical to the official file (first {len(ref) // 1048576} MB compared)"
                                         if same else "differs from the official file (likely another print/edition)")
            else:
                rec["official_match"] = "no official copy available to compare"
            if label.endswith(":loose") and not rec["official_match"].startswith("identical"):
                rec["attempts"].append(f"{label}: label differs and not proven identical, skipped")
                rec["official_match"] = ""
                continue
            if rec["official_match"].startswith("differs") and not backup.exists():
                tmp.replace(backup)  # different print: use only if nothing closer to the official file turns up
                backup_meta.update(source=label, source_url=info.get("final_url", url), official_match=rec["official_match"], **meta)
                rec["attempts"].append(f"{label}: differs from official file, kept as last resort")
                rec["official_match"] = ""
                continue
        tmp.rename(dest)
        h = hashlib.sha256(dest.read_bytes()).hexdigest()
        rec.update(status="ok", source=label, source_url=info.get("final_url", url), file=dest.name, sha256=h, **meta)
        break
    if rec["status"] != "ok" and backup.exists():
        backup.rename(dest)
        rec.update(status="ok", file=dest.name, sha256=hashlib.sha256(dest.read_bytes()).hexdigest(), **backup_meta)
    for f in (tmp, prefix, backup):
        if f.exists():
            f.unlink()
    if not cands:
        rec["attempts"].append("no link on NCCD and no fallback source")
    results.append(rec)
    print(f"[{n+1}/{len(rows)}] {rec['status']:7} G{r['grade_key']} {r['subject_en'] or r['subject_ar']} S{r['semester']} {r['type']}"
          f" <- {rec['source'] or '; '.join(rec['attempts'])[:200]} {rec['official_match']}", flush=True)

json.dump(results, open(OUT / "results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
ok = sum(1 for x in results if x["status"] == "ok")
print(f"\n{ok}/{len(results)} books downloaded and verified", flush=True)
