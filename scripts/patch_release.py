#!/usr/bin/env python3
"""Apply catalog/patches.json to the release zips (renames, moves, deletions,
additions, page-order fixes found during the cover-by-cover review), then
update reports/results-*.json and rebuild REPORT.md / INDEX.csv.

Env: GITHUB_REPOSITORY, TAG.  Writes patched zips to patched/.
"""
import csv, glob, hashlib, json, os, pathlib, re, subprocess, sys, tempfile, zipfile
import unicodedata
import requests

NFC = lambda s: unicodedata.normalize("NFC", s)

REPO, TAG = os.environ["GITHUB_REPOSITORY"], os.environ["TAG"]
ROOT = "Jordan-School-Books-2025-2026/"
OUT = pathlib.Path("patched")
OUT.mkdir(exist_ok=True)
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 jordan-school-books/1.0", "Referer": "https://www.minhaji.net/"})

patches = json.load(open("catalog/patches.json", encoding="utf-8"))
index = list(csv.DictReader(open("reports/INDEX.csv", encoding="utf-8-sig")))
results = {f: json.load(open(f, encoding="utf-8")) for f in glob.glob("reports/results-*.json")}


def pdf_check(path):
    size = path.stat().st_size
    with open(path, "rb") as fh:
        head = fh.read(1024)
        fh.seek(max(0, size - 2048))
        tail = fh.read()
    p = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True)
    m = re.search(r"^Pages:\s+(\d+)", p.stdout, re.M)
    if b"%PDF" not in head or b"%%EOF" not in tail or not m:
        raise SystemExit(f"not a complete PDF: {path}")
    return int(m.group(1)), size


def result_by_sha(sha):
    for f, rs in results.items():
        for r in rs:
            if r.get("sha256") == sha:
                return r
    return None


def add_note(row, note):
    if note:
        row["type_note"] = "; ".join(x for x in (row.get("type_note"), note) if x)


for zname, ops in patches.items():
    src = OUT / f"orig-{zname}"
    with S.get(f"https://github.com/{REPO}/releases/download/{TAG}/{zname}", stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(src, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)
    zin = zipfile.ZipFile(src)
    names = {NFC(n) for n in zin.namelist()}
    # NCCD file names sometimes spell hamza letters in decomposed form; compare in NFC
    ren = {NFC(ROOT + o): (NFC(ROOT + n), meta) for o, n, meta in ops.get("rename", [])}
    dele = {NFC(ROOT + d) for d in ops.get("delete", [])}
    # Re-runs: drop corrections that are already applied
    ren = {o: v for o, v in ren.items() if not (o not in names and v[0] in names)}
    dele = {d for d in dele if d in names}
    adds = [a for a in ops.get("add", []) if NFC(ROOT + a["path"]) not in names]
    absent = [x for x in list(ren) + list(dele) if x not in names]
    if absent:
        raise SystemExit(f"{zname}: entries not found: {absent}")
    with zipfile.ZipFile(OUT / zname, "w", zipfile.ZIP_STORED) as zout:
        for info in zin.infolist():
            name = NFC(info.filename)
            row = next((x for x in index if NFC(x["file"]) == name), None)
            if name in dele:
                if row:
                    index.remove(row)
                    res = result_by_sha(row["sha256"])
                    if res:
                        res["status"] = "duplicate"
                print(f"{zname}: removed {name}")
                continue
            data = zin.read(info)
            new, meta = ren.get(name, (name, {}))
            if meta.get("first_page_to_end"):
                with tempfile.TemporaryDirectory() as td:
                    a, b = pathlib.Path(td) / "a.pdf", pathlib.Path(td) / "b.pdf"
                    a.write_bytes(data)
                    subprocess.run(["qpdf", "--warning-exit-0", str(a), "--pages", str(a), "2-z,1", "--", str(b)], check=True)
                    pages, size = pdf_check(b)
                    data = b.read_bytes()
                if row:
                    row.update(pages=str(pages), size=str(size), sha256=hashlib.sha256(data).hexdigest())
            zi = zipfile.ZipInfo(new, date_time=info.date_time)
            zi.compress_type = zipfile.ZIP_STORED
            zout.writestr(zi, data)
            if new != name:
                print(f"{zname}: {name.rsplit('/', 3)[-3:]} -> {new.rsplit('/', 3)[-3:]}")
            if row:
                old_sha = row["sha256"]
                row["file"] = new
                for k in ("subject_en", "subject_ar"):
                    if k in meta:
                        row[k] = meta[k]
                add_note(row, meta.get("note"))
                res = result_by_sha(old_sha)
                if res:
                    for k in ("subject_en", "subject_ar"):
                        if k in meta:
                            res[k] = meta[k]
                    res["sha256"] = row["sha256"]
        for add in adds:
            tmp = OUT / "add.pdf"
            with S.get(add["url"], stream=True, timeout=600) as r:
                r.raise_for_status()
                with open(tmp, "wb") as fh:
                    for chunk in r.iter_content(1 << 20):
                        fh.write(chunk)
            pages, size = pdf_check(tmp)
            sha = hashlib.sha256(tmp.read_bytes()).hexdigest()
            zout.write(tmp, ROOT + add["path"])
            grade_en = add["path"].split("/")[0].split(" - ")[0]
            index.append({"file": ROOT + add["path"], "grade_en": grade_en, "subject_en": add["subject_en"],
                          "subject_ar": add["subject_ar"], "semester": add["semester"], "type": add["type"],
                          "pages": str(pages), "size": str(size), "source": "mirror:minhaji.net",
                          "official_match": "no official copy available to compare",
                          "official_url": "https://www.nccd.gov.jo" + requests.utils.quote(add["official_path"]),
                          "source_url": add["url"], "sha256": sha, "type_note": add.get("note", "")})
            for rs in results.values():
                for r in rs:
                    if r["grade_key"] == add["grade_key"] and r.get("path") == add["official_path"]:
                        r.update(status="ok", source="mirror:minhaji.net", source_url=add["url"], sha256=sha,
                                 pages=pages, size=size, official_match="no official copy available to compare",
                                 type=add["type"], type_note=add.get("note", ""))
            tmp.unlink()
            print(f"{zname}: added {add['path']}")
    src.unlink()

for f, rs in results.items():
    json.dump(rs, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# Rebuild REPORT.md / INDEX.csv with report.py from the updated data
art = pathlib.Path("art")
for f in results:
    d = art / pathlib.Path(f).stem
    d.mkdir(parents=True, exist_ok=True)
    (d / "results.json").write_text(pathlib.Path(f).read_text(encoding="utf-8"), encoding="utf-8")
(art / "all").mkdir(parents=True, exist_ok=True)
json.dump(index, open(art / "all" / "index.json", "w", encoding="utf-8"), ensure_ascii=False)
subprocess.run([sys.executable, "scripts/report.py", "art", "final"], check=True)
