# Plan: Jordanian school textbooks (PDF), all grades → Google Drive

Goal: collect the official Jordanian school textbooks for every grade as PDFs,
organize them into a clean folder tree, and hand them over in a form that can be
uploaded to Google Drive in one go and shared with a single link.

## 1. Source

The only source is the **National Center for Curriculum Development (NCCD)**,
which publishes every current textbook as a free PDF:

- Grade index pages: `https://www.nccd.gov.jo/ar/pages/TextBooksGrade/<id>`
  - Confirmed: 68 = Grade 1, 69 = Grade 2, 70 = Grade 3, 71 = Grade 4,
    72 = Grade 5, 73 = Grade 6, 77 = Grade 10, 83 = Grade 12 (academic track)
  - Expected (to be confirmed): 74–76 = Grades 7–9, 78–82 = Grade 11/12 tracks

Third-party mirrors (awa2el.net, jo1jo.com, …) are **not** used. They can be
outdated or edited. Every file must come from nccd.gov.jo.

## 2. Scope

| Included by default | Optional (on request) |
| --- | --- |
| Grades 1–12, including every Grade 11/12 track NCCD lists | Teacher's guides (دليل المعلم), which roughly double the size |
| Every subject NCCD publishes for each grade | Kindergarten, if NCCD lists it |
| Both semesters (الفصل الأول / الثاني) | |
| Student book (كتاب الطالب) + activity/workbook (كتاب الأنشطة والتمارين) | |

## 3. Folder structure

```
Jordan-School-Books-2025-2026/
├── README.txt                      ← source, date collected, how to navigate
├── INDEX.csv                       ← one row per book: grade, subject, semester, type, file, source URL, pages, size, sha256
├── Grade 01 - الصف الأول/
│   ├── Arabic - اللغة العربية/
│   │   ├── Semester 1 - الفصل الأول/
│   │   │   ├── Student Book - كتاب الطالب.pdf
│   │   │   └── Activity Book - كتاب الأنشطة والتمارين.pdf
│   │   └── Semester 2 - الفصل الثاني/
│   ├── Mathematics - الرياضيات/
│   ├── Science - العلوم/
│   ├── English - اللغة الإنجليزية/
│   ├── Islamic Education - التربية الإسلامية/
│   └── …
├── Grade 02 - الصف الثاني/
├── …
├── Grade 11 - Academic - الحادي عشر الأكاديمي/
└── Grade 12 - Academic - الثاني عشر الأكاديمي/
```

Folder names are bilingual and zero-padded so they sort correctly in Drive.

## 4. Pipeline

1. **Discover**: crawl each grade page and its subject/book pages, then write
   `manifest.csv` (grade, track, subject, semester, book type, title, PDF URL).
2. **Review the manifest**: count books per grade, flag missing core subjects
   or semesters, and check nothing is duplicated. Nothing is downloaded until
   the catalog looks complete.
3. **Download**: 2–3 parallel connections to be polite, retries with backoff,
   and resume support so a re-run only fetches what is missing.
4. **Verify**: every file must start with `%PDF`, open in `pdfinfo` and report
   a page count. Record size and sha256. Any failure is retried or listed in
   the final report; it is never silently skipped.
5. **Organize**: build the folder tree, `INDEX.csv` and `README.txt`.
6. **Package**: one `.zip` per grade (each under 2 GB), plus `SHA256SUMS.txt`.
7. **Publish**: a GitHub Actions workflow in this repo creates a Release with
   one zip per grade. The bulk download runs on GitHub's servers and the
   result comes straight from GitHub's download links.

## 5. Handover to Google Drive

1. Download the per-grade zips from the repo's **Releases** page. A computer
   is recommended because the total is expected to be several GB.
2. Extract them into one folder, `Jordan-School-Books-2025-2026`.
3. Drag that folder into drive.google.com. Drive keeps the subfolders.
4. Right-click the folder → Share → General access: **Anyone with the link →
   Viewer**, then copy the link.
5. Check that your Drive has enough free space: the free tier is 15 GB,
   shared with Gmail and Photos.

## 6. Notes

- The books are © NCCD and published free for everyone. `README.txt` credits
  NCCD and links to the official site, which always has the latest editions.
- This repo stays **public** (owner's decision), so the Release zips can be
  downloaded by anyone. Each zip's README credits NCCD as the source.
- Quick win while this runs: the official NCCD site https://www.nccd.gov.jo
  can be sent to your friend right away. Its textbooks section has a page per
  grade, for example https://www.nccd.gov.jo/ar/pages/TextBooksGrade/68 for
  Grade 1.

## 7. Decisions

- Scope: student books + activity books only (no teacher's guides, no KG).
- Access: the owner is allowing `nccd.gov.jo` / `www.nccd.gov.jo` in this
  environment's network settings.
- Repo visibility: stays public.

## 8. Status / blockers

- [ ] **Blocked:** this cloud session's network policy denies `nccd.gov.jo` and
      `www.nccd.gov.jo`, so the catalog cannot be crawled or verified from here
      yet.
- [ ] Discover + manifest
- [ ] Downloader, verifier and packager scripts
- [ ] GitHub Actions workflow → Release
- [ ] Final report (counts per grade, total size, anything missing)
