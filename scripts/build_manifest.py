#!/usr/bin/env python3
"""Turn archived NCCD grade pages into catalog/manifest.csv.

Every book card on a grade page carries subject, grade, semester, book type
and a direct PDF link. NCCD's own type labels are occasionally swapped (e.g. an
Activity Book labelled as the student book), so the type is cross-checked
against the PDF file name, which usually says PB/AB/TB, طالب/تمارين/دليل, etc.

Usage: build_manifest.py [catalog_dir]
"""
import csv, html, re, sys, pathlib
from urllib.parse import quote

CAT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "catalog")

GRADES = {  # NCCD page id -> (folder sort key, English, Arabic)
    68: (1, "Grade 01", "الصف الأول"), 69: (2, "Grade 02", "الصف الثاني"),
    70: (3, "Grade 03", "الصف الثالث"), 71: (4, "Grade 04", "الصف الرابع"),
    72: (5, "Grade 05", "الصف الخامس"), 73: (6, "Grade 06", "الصف السادس"),
    74: (7, "Grade 07", "الصف السابع"), 75: (8, "Grade 08", "الصف الثامن"),
    76: (9, "Grade 09", "الصف التاسع"), 77: (10, "Grade 10", "الصف العاشر"),
    117: (11, "Grade 11 Academic", "الصف الحادي عشر - المسار الأكاديمي"),
    83: (12, "Grade 12 Academic", "الصف الثاني عشر - المسار الأكاديمي"),
}

SUBJECTS = {  # normalized Arabic subject -> English
    "اللغه العربيه": "Arabic", "اللغه الانجليزيه": "English", "الرياضيات": "Mathematics",
    "العلوم": "Science", "التربيه الاسلاميه": "Islamic Education",
    "الدراسات الاجتماعيه": "Social Studies", "التربيه الرياضيه": "Physical Education",
    "التربيه الفنيه والموسيقيه والمسرحيه": "Art, Music and Theatre",
    "المهارات الرقميه": "Digital Skills", "التربيه المهنيه": "Vocational Education",
    "التربيه الوطنيه والمدنيه": "National and Civic Education", "التاريخ": "History",
    "الجغرافيا": "Geography", "الفيزياء": "Physics", "الكيمياء": "Chemistry",
    "الاحياء": "Biology", "علوم الارض والبيئه": "Earth and Environmental Science",
    "الثقافه الماليه": "Financial Literacy", "اللغه الفرنسيه": "French",
    "التربيه المسيحيه": "Christian Education", "الثقافه العامه": "General Culture",
    "تاريخ الاردن": "History of Jordan", "الفلسفه": "Philosophy",
    "علم الاجتماع": "Sociology", "علم النفس": "Psychology", "الاقتصاد": "Economics",
    "الحاسوب": "Computer Science", "الثقافه العسكريه": "Military Culture",
    "الرياضيات المتقدمه": "Advanced Mathematics", "الرياضيات الاساسيه": "Basic Mathematics",
    "اللغه العربيه - التخصص": "Arabic (Specialized)", "التربيه الصحيه": "Health Education",
    "الرياضيات/الاعمال": "Business Mathematics", "العلوم الحياتيه": "Biology",
    "اللغه العربيه /الادب": "Arabic Literature",
    "اللغه العربيه /النحو والصرف وموسيقا الشعر": "Arabic Grammar and Prosody",
    "تاريخ": "History", "جغرافيا": "Geography", "علوم النفس والاجتماع": "Psychology and Sociology",
}

INCLUDED = ("student", "activity", "supplement")  # teacher guides and answer keys are left out


def norm(s):
    s = re.sub(r"[ً-ْـ]", "", s or "")  # tashkeel, tatweel
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
    return " ".join(s.split())


def label_type(lbl):
    n = norm(lbl)
    if "دليل" in n:
        return "teacher"
    if "حلول" in n or "اجابات" in n:
        return "answers"
    if "اوراق العمل" in n or "مواد معززه" in n:
        return "supplement"
    if "تمارين" in n or "نشاط" in n or "انشطه" in n:
        return "activity"
    if "طالب" in n or n.startswith("كتاب"):
        return "student"
    return None


def display_name(btype, lbl):
    n = norm(lbl)
    if btype == "student":
        return "Student Book - كتاب الطالب" if "طالب" in n or not n else f"Student Book - {lbl}"
    if btype == "activity":
        return "Activity Book - كتاب الأنشطة والتمارين"
    return f"Supporting Material - {lbl}"


def filename_type(path):
    name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    n, low = norm(name), name.lower()
    toks = [t for t in re.split(r"[\s_.\-()]+", name) if t]
    hits = set()
    if "دليل" in n or "teacher" in low or any(re.fullmatch(r"(TE|TG|TB)\d*", t, re.I) for t in toks):
        hits.add("teacher")
    if any(k in n for k in ("تمارين", "نشاط", "انشطه")) or "activity" in low or "workbook" in low \
            or any(re.fullmatch(r"(AB|WB|EX)\d*", t, re.I) for t in toks):
        hits.add("activity")
    if "طالب" in n or "pupil" in low or "student" in low \
            or any(re.fullmatch(r"(PB|SB|SE|ST)\d*", t, re.I) for t in toks):
        hits.add("student")
    return hits.pop() if len(hits) == 1 else None


def semester(lbl):
    n = norm(lbl)
    if "الثاني" in n:
        return 2
    if "الاول" in n:
        return 1
    return 0


def field(card, key):
    m = re.search(r'lbl' + key + r'_\d+"[^>]*>([^<]*)<', card)
    return html.unescape(m.group(1)).strip() if m else ""


rows = []
for gid, (gkey, gen, gar) in GRADES.items():
    f = CAT / "snapshots" / f"grade_{gid}.html"
    if not f.exists():
        print(f"!! missing snapshot for grade page {gid} ({gen})")
        continue
    page = f.read_text(encoding="utf-8")
    for i, card in enumerate(page.split('class="col-md-4 bookposition"')[1:]):
        subj_ar = field(card, "Title")
        lbl = field(card, "Type")
        m = re.search(r'<a href="([^"]+)" target="_blank">', card)
        href = html.unescape(m.group(1)).strip() if m else ""
        is_pdf = href.lower().endswith(".pdf")
        lt, ft = label_type(lbl), (filename_type(href) if is_pdf else None)
        # File-name hints only arbitrate student vs activity (NCCD sometimes swaps these labels)
        if lt in (None, "student", "activity") and ft in ("student", "activity"):
            btype = ft
        else:
            btype = lt or ft or "unknown"
        rows.append({
            "grade_key": gkey, "grade_en": gen, "grade_ar": gar, "nccd_grade_id": gid,
            "subject_ar": subj_ar, "subject_en": SUBJECTS.get(norm(subj_ar), ""),
            "semester": semester(field(card, "Semester")),
            "type": btype, "nccd_label": lbl, "display_name": display_name(btype, lbl),
            "type_note": "" if btype == lt else f"label says {lt}, file name says {ft}",
            "path": href if is_pdf else "",
            "official_url": ("https://www.nccd.gov.jo" + quote(href, safe="/()&,'+")) if is_pdf else "",
            "card": i,
        })

with open(CAT / "manifest_all.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

wanted, seen = [], {}
for r in rows:
    if r["type"] not in INCLUDED:
        continue
    k = (r["grade_key"], r["path"]) if r["path"] else None
    if k and k in seen:  # NCCD lists a few files twice; keep the entry whose label matches the file
        prev = seen[k]
        if prev["type_note"] and not r["type_note"]:
            wanted[wanted.index(prev)] = r
            seen[k] = r
        print(f"  duplicate link dropped: {r['grade_en']} {r['subject_ar']} {r['path'].rsplit('/',1)[-1]}")
        continue
    if k:
        seen[k] = r
    wanted.append(r)
with open(CAT / "manifest.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(wanted)

# Report
from collections import Counter, defaultdict
print(f"{len(rows)} cards total; {len(wanted)} books in manifest.csv (student, activity, supporting material)")
print("type counts:", Counter(r["type"] for r in rows))
for r in rows:
    if r["type_note"]:
        print(f"  relabelled: {r['grade_en']} {r['subject_ar']} S{r['semester']}: {r['type_note']} ({r['path'].rsplit('/',1)[-1]})")
    if not r["path"]:
        print(f"  NO LINK on NCCD: {r['grade_en']} {r['subject_ar']} S{r['semester']} {r['nccd_label']}")
unknown = sorted({r["subject_ar"] for r in rows if not r["subject_en"]})
if unknown:
    print("subjects without English name:", unknown)
by = defaultdict(lambda: Counter())
for r in wanted:
    by[r["grade_key"]][r["subject_en"] or r["subject_ar"]] += 1
for g in sorted(by):
    print(f"G{g:02d}: {sum(by[g].values())} books | " + ", ".join(f"{k}:{v}" for k, v in sorted(by[g].items())))
