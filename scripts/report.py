#!/usr/bin/env python3
"""Combine per-grade results into REPORT.md and INDEX.csv.

Usage: report.py <artifacts_dir> <out_dir>
Expects <artifacts_dir>/*/results.json and optional */index.json.
"""
import csv, json, pathlib, sys
from collections import defaultdict

art, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
results, index = [], []
for f in sorted(art.glob("*/results.json")):
    results += json.load(open(f, encoding="utf-8"))
for f in sorted(art.glob("*/index.json")):
    index += json.load(open(f, encoding="utf-8"))
results.sort(key=lambda r: (int(r["grade_key"]), r["subject_en"] or r["subject_ar"], str(r["semester"]), r["type"]))
index.sort(key=lambda r: r["file"])

with open(out / "INDEX.csv", "w", newline="", encoding="utf-8-sig") as fh:
    cols = ["file", "grade_en", "subject_en", "subject_ar", "semester", "type", "pages", "size", "source",
            "official_url", "source_url", "sha256", "type_note"]
    w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    w.writerows(index)

by = defaultdict(list)
for r in results:
    by[(int(r["grade_key"]), r["grade_en"])].append(r)
ok_all = sum(r["status"] == "ok" for r in results)
mb = sum(r.get("size", 0) or 0 for r in results if r["status"] == "ok") / 1e6
src = defaultdict(int)
for r in results:
    if r["status"] == "ok":
        src[r["source"].split(":")[0]] += 1

lines = ["# Download report", "",
         f"**{ok_all} of {len(results)}** student/activity books downloaded and verified "
         f"({mb/1000:.2f} GB).", "",
         "Sources: " + ", ".join(f"{k}: {v}" for k, v in sorted(src.items())), "",
         "| Grade | Books OK | Missing | Size (MB) |", "| --- | --- | --- | --- |"]
for (g, name), rs in sorted(by.items()):
    ok = [r for r in rs if r["status"] == "ok"]
    lines.append(f"| {name} | {len(ok)} | {len(rs) - len(ok)} | {sum(r.get('size', 0) or 0 for r in ok)/1e6:.0f} |")
miss = [r for r in results if r["status"] != "ok"]
if miss:
    lines += ["", "## Missing", "", "| Grade | Subject | Sem | Type | Why |", "| --- | --- | --- | --- | --- |"]
    for r in miss:
        why = "; ".join(r["attempts"])[:300].replace("|", "/")
        lines.append(f"| {r['grade_en']} | {r['subject_en'] or ''} {r['subject_ar']} | {r['semester']} | {r['type']} | {why} |")
relabel = [r for r in results if r.get("type_note")]
if relabel:
    lines += ["", "## Type labels corrected from file names", ""]
    lines += [f"- {r['grade_en']} {r['subject_en'] or r['subject_ar']} S{r['semester']}: {r['type_note']}" for r in relabel]
(out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
