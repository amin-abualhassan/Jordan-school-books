#!/usr/bin/env python3
"""Match mirror files (catalog/minhaji.csv) to manifest books -> catalog/fallbacks.csv.

A mirror file is matched on grade + subject + semester + book type. These are
only used when no complete official copy can be retrieved; download.py then
checks the mirror file against any partial official copy it found.
"""
import csv, re, pathlib, sys
from collections import defaultdict

CAT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "catalog")


def norm(s):
    s = re.sub(r"[ً-ْـ]", "", s or "")
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
    return " ".join(s.split())


RULES = [  # (needle in normalized Arabic subject, canonical subject); first match wins
    ("الاعمال", "business-math"), ("رياضيات", "math"), ("رياضيه", "pe"),
    ("تاريخ الاردن", "jordan-history"), ("تاريخ", "history"), ("جغرافيا", "geography"),
    ("حياتيه", "biology"), ("احياء", "biology"), ("فيزياء", "physics"), ("كيمياء", "chemistry"),
    ("الارض", "earth"), ("النفس", "psych-soc"), ("الاجتماع", "psych-soc"),
    ("اجتماعيه", "social"), ("اسلاميه", "islamic"), ("انجليزي", "english"),
    ("الادب", "arabic-lit"), ("النحو", "arabic-grammar"), ("عربي", "arabic"), ("لغتي", "arabic"),
    ("رقميه", "digital"), ("حاسوب", "digital"), ("فنيه", "art"), ("موسيق", "art"),
    ("مهنيه", "vocational"), ("وطنيه", "civic"), ("ماليه", "finance"), ("فلسفه", "philosophy"),
    ("فرنسي", "french"), ("علوم", "science"),
]


def subject_key(s):
    n = norm(s)
    for needle, key in RULES:
        if needle in n:
            return key
    return n


def type_key(s):
    n = norm(s)
    low = n.lower()
    if "teacher" in low:
        return "teacher"
    if "activity" in low or "workbook" in low:
        return "activity"
    if "pupil" in low or "student" in low:
        return "student"
    if "دليل" in n:
        return "teacher"
    if "حلول" in n or "اجابات" in n:
        return "answers"
    if "اوراق" in n:
        return "supplement"
    if "تمارين" in n or "نشاط" in n or "انشطه" in n:
        return "activity"
    if "طالب" in n or "كتاب" in n:
        return "student"
    return None


def sem_key(s):
    n = norm(s)
    if "الفصل الثاني" in n or "الجزء الثاني" in n:
        return 2
    if "الفصل الاول" in n or "الجزء الاول" in n:
        return 1
    return 0


mirror = defaultdict(list)
src = CAT / "minhaji.csv"
groups = defaultdict(list)
for r in csv.DictReader(open(src, encoding="utf-8")):
    groups[(r["grade_key"], r["subject"])].append(r)
for (g, subj), rs in groups.items():
    # minhaji sometimes labels the semester-2 book "الفصل الأول" again; when a list has the same
    # (type, semester) label twice for different lessons and the other semester is absent, the
    # later entry is the semester-2 book.
    labels = defaultdict(list)
    for r in rs:
        labels[(type_key(r["label"]), sem_key(r["label"]))].append(r)
    for (t, s), lst in labels.items():
        lessons = list(dict.fromkeys(x["lesson_id"] for x in lst))
        if t and s == 1 and len(lessons) == 2 and not labels.get((t, 2)):
            for x in lst:
                if x["lesson_id"] == lessons[1]:
                    x["label"] += " [semester 2 inferred from list order]"
                    x["sem_override"] = 2
    for r in rs:
        t = type_key(r["label"])
        if not t:
            continue
        sk, nl = subject_key(subj), norm(r["label"])
        if sk == "math" and "اعمال" in nl:
            sk = "business-math"
        if sk == "arabic" and g == "12":
            sk = "arabic-lit" if "الادب" in nl else "arabic-grammar" if "النحو" in nl else sk
        mirror[(g, sk, t)].append((r.get("sem_override") or sem_key(r["label"]), r))

ALIASES = {"history": ["jordan-history"], "jordan-history": ["history"]}


def track(s):
    n = norm(s)
    return "voc" if "مهني" in n else "acad" if "اكاديمي" in n else None


out, unmatched = [], []
manifest = list(csv.DictReader(open(CAT / "manifest.csv", encoding="utf-8")))
for m in manifest:
    sk = subject_key(m["subject_ar"])
    # G12 Arabic is split into Literature / Grammar books in both sources
    if sk == "arabic" and m["grade_key"] == "12":
        sk = "arabic-lit" if "ادب" in norm(m["nccd_label"]) else "arabic-grammar" if "نحو" in norm(m["nccd_label"]) else sk
    sem, g = int(m["semester"]), m["grade_key"]
    mtrack = track(m["path"])
    strict, loose = [], []
    for subj in [sk] + ALIASES.get(sk, []):
        for t in ("student", "activity", "supplement"):
            for s, r in mirror.get((g, subj, t), []):
                rt = track(r["label"])
                if mtrack and rt and mtrack != rt:
                    continue
                exact = subj == sk and t == m["type"] and (s == sem or s == 0 or sem == 0)
                (strict if exact else loose).append(r)
    if not strict:  # aliases count as strict when the subject itself has nothing
        strict = [r for r in loose if type_key(r["label"]) == m["type"] and sem_key(r["label"]) in (sem, 0)]
        loose = [r for r in loose if r not in strict]
    key = m["path"] or f"G{g}|{m['subject_ar']}|S{m['semester']}|{m['type']}"
    for r, kind in [(r, "strict") for r in strict] + [(r, "loose") for r in loose if m["type"] != "supplement"]:
        out.append({"grade_key": g, "path": m["path"], "key": key, "url": r["url"], "mirror": "minhaji.net",
                    "match": kind, "mirror_label": f"{r['subject']} | {r['label']}"})
    if not strict:
        unmatched.append(m)

with open(CAT / "fallbacks.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=["grade_key", "path", "key", "url", "mirror", "match", "mirror_label"])
    w.writeheader()
    w.writerows(out)
print(f"{len(manifest) - len(unmatched)}/{len(manifest)} books have a direct mirror match "
      f"({sum(o['match'] == 'strict' for o in out)} strict + {sum(o['match'] == 'loose' for o in out)} loose links; "
      "loose links are used only if byte-identical to the official file)")
for m in unmatched:
    print(f"  no mirror: G{m['grade_key']} {m['subject_ar']} S{m['semester']} {m['type']} [{m['nccd_label']}]")
