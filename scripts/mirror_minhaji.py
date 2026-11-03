#!/usr/bin/env python3
"""Map minhaji.net's textbook lists ("الكتب المقررة") for Grades 1-12.

minhaji.net (Amman) re-hosts the NCCD textbooks. Structure:
  /lesson/<grade id>              -> subject links
  /lesson/<subject id>            -> link "الكتب المقررة" -> /lesson/<books id>
  /lesson/<books id>              -> one link per book, labelled e.g. "كتاب الطالب - الفصل الأول"
  /lesson/<book id>               -> /download_files/<n>  (file served at /download/<n>)

Usage: mirror_minhaji.py <out_csv>
"""
import csv, re, sys, time, html
import requests

BASE = "https://www.minhaji.net"
GRADES = {1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8, 8: 9, 9: 10, 10: 11, 11: 13, 12: 14}
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) jordan-school-books/1.0"


def get(path):
    for i in range(4):
        try:
            r = S.get(BASE + path, timeout=60)
            if r.status_code == 200:
                time.sleep(0.6)
                return r.text
        except Exception as e:
            print("  !", path, e, flush=True)
        time.sleep(5 * (i + 1))
    return ""


def links(page):
    out = []
    for href, txt in re.findall(r'<a[^>]+href="(/lesson/\d+[^"]*)"[^>]*>(.*?)</a>', page, re.S):
        t = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", txt)).split())
        out.append((href, t))
    return out


def module_links(page, title):
    """Links inside the module box whose title contains `title`."""
    i = page.find('class="module"')
    while i != -1:
        j = page.find('class="module"', i + 10)
        block = page[i: j if j != -1 else len(page)]
        head = re.search(r'class="title">(.*?)</div>', block, re.S)
        if head and title in re.sub(r"<[^>]+>", " ", head.group(1)):
            return links(block)
        i = j
    return []


rows = []
only = [int(a) for a in sys.argv[2:]] or list(GRADES)
for grade in only:
    gid = GRADES[grade]
    gpage = get(f"/lesson/{gid}")
    subjects = [(h, t) for h, t in links(gpage) if re.match(r"/lesson/\d+/", h) and t and t != "الرئيسية"]
    seen = set()
    while subjects:
        shref, sname = subjects.pop(0)
        sid = re.match(r"/lesson/(\d+)", shref).group(1)
        if sid in seen or sid == str(gid):
            continue
        seen.add(sid)
        spage = get(f"/lesson/{sid}")
        books = [(h, t) for h, t in links(spage) if "الكتب المقررة" in t or "الكتب المدرسية" in t]
        if not books:
            if "المسار الأكاديمي" in sname and "قديم" not in sname:
                # Grade 12 groups its subjects one level deeper, under the academic track
                subs = [(h, t) for h, t in links(spage) if re.match(r"/lesson/\d+/", h) and t
                        and not t.startswith("الدرس") and re.match(r"/lesson/(\d+)", h).group(1) not in seen]
                print(f"G{grade} {sname}: descending into {len(subs)} sub-sections", flush=True)
                subjects.extend(subs)
            else:
                print(f"G{grade} {sname}: no textbook section", flush=True)
            continue
        bid = re.match(r"/lesson/(\d+)", books[0][0]).group(1)
        bpage = get(f"/lesson/{bid}")
        entries = module_links(bpage, "الكتب") or [(h, t) for h, t in links(bpage) if "كتاب" in t]
        for lhref, label in entries:
            lid = re.match(r"/lesson/(\d+)", lhref).group(1)
            lpage = get(f"/lesson/{lid}")
            for n in dict.fromkeys(re.findall(r'href="/download_files/(\d+)"', lpage)):
                rows.append({"grade_key": grade, "subject": sname, "label": label, "lesson_id": lid,
                             "download_id": n, "url": f"{BASE}/download/{n}"})
            print(f"G{grade} {sname} | {label} -> {re.findall('/download_files/([0-9]+)', lpage)}", flush=True)

import os
mode = "a" if len(sys.argv) > 2 and os.path.exists(sys.argv[1]) else "w"
with open(sys.argv[1], mode, newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=["grade_key", "subject", "label", "lesson_id", "download_id", "url"])
    if mode == "w":
        w.writeheader()
    w.writerows(rows)
print(f"{len(rows)} files", flush=True)
