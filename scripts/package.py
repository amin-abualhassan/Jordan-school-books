#!/usr/bin/env python3
"""Arrange verified PDFs into the bilingual folder tree and zip them.

Usage: package.py <download_dir> <out_dir>
Reads <download_dir>/results.json (from download.py), writes:
  <out_dir>/tree/Jordan-School-Books-2025-2026/Grade .. /Subject .. /Semester .. /<Type>.pdf
  <out_dir>/zips/<Grade-NN...>.zip   (split into parts if a grade exceeds ~1.9 GB)
  <out_dir>/index.json               (one entry per placed file)
"""
import json, os, pathlib, re, shutil, sys, zipfile

ROOT_NAME = "Jordan-School-Books-2025-2026"
MAX_ZIP = 1_900_000_000
SEMS = {"1": "Semester 1 - الفصل الأول", "2": "Semester 2 - الفصل الثاني", "0": "Full Year - العام الدراسي كاملا"}

dl, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
results = json.load(open(dl / "results.json", encoding="utf-8"))
tree = out / "tree" / ROOT_NAME
README = pathlib.Path(__file__).with_name("README_drive.txt")


def clean(s):
    s = re.sub(r'[\\/:*?"<>|]+', "-", s)
    return " ".join(s.split()).strip(" .-")


def place(r):
    grade = clean(f"{r['grade_en']} - {r['grade_ar']}")
    subj = clean(f"{r['subject_en']} - {r['subject_ar']}" if r["subject_en"] else r["subject_ar"])
    sem = SEMS.get(str(r["semester"]), SEMS["0"])
    return pathlib.Path(grade) / subj / sem, clean(r["display_name"])


from collections import Counter
ok_rows = [r for r in results if r["status"] == "ok"]
clash = Counter(place(r) for r in ok_rows)
index, used = [], set()
for r in ok_rows:
    folder, base = place(r)
    if clash[(folder, base)] > 1:  # two editions/versions of the same book: keep NCCD's file name to tell them apart
        stem = clean(r["path"].rsplit("/", 1)[-1].rsplit(".", 1)[0])[:80]
        base = f"{base} ({stem})"
    rel = folder / f"{base}.pdf"
    k = 2
    while str(rel) in used:
        rel = folder / f"{base} ({k}).pdf"
        k += 1
    used.add(str(rel))
    dest = tree / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(dl / "files" / r["file"]), dest)
    index.append({**{k2: r[k2] for k2 in ("grade_key", "grade_en", "grade_ar", "subject_en", "subject_ar",
                                           "semester", "type", "nccd_label", "pages", "size", "sha256", "source",
                                           "source_url", "official_url", "type_note")},
                  "file": str(pathlib.Path(ROOT_NAME) / rel)})

json.dump(index, open(out / "index.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# Zip per grade (stored: PDFs are already compressed). Split by subject if too big.
zdir = out / "zips"
zdir.mkdir(parents=True, exist_ok=True)
for gdir in sorted(p for p in tree.iterdir() if p.is_dir()):
    slug = re.sub(r"[^A-Za-z0-9]+", "-", gdir.name.split(" - ")[0]).strip("-")
    files = sorted(f for f in gdir.rglob("*.pdf"))
    bins, cur, size = [], [], 0
    for f in files:
        s = f.stat().st_size
        if cur and size + s > MAX_ZIP:
            bins.append(cur)
            cur, size = [], 0
        cur.append(f)
        size += s
    if cur:
        bins.append(cur)
    for i, b in enumerate(bins, 1):
        name = f"{slug}.zip" if len(bins) == 1 else f"{slug}-part{i}.zip"
        with zipfile.ZipFile(zdir / name, "w", zipfile.ZIP_STORED) as z:
            if README.exists():
                z.write(README, f"{ROOT_NAME}/README.txt")
            for f in b:
                z.write(f, str(f.relative_to(tree.parent)))
        print(f"{name}: {len(b)} files, {(zdir / name).stat().st_size / 1e6:.0f} MB")
