# Upload the textbook release into a Google Drive folder (run inside Google Colab).
# Downloads each grade zip from the GitHub release, unpacks it one file at a time,
# and uploads the PDFs into the same folder tree in Drive. Safe to re-run: files
# already in Drive with the same name and size are skipped.
import os, sys, time, socket, zipfile, unicodedata, pathlib, requests

FOLDER = "application/vnd.google-apps.folder"
ROOT_PREFIX = "Jordan-School-Books-2025-2026/"
NFC = lambda s: unicodedata.normalize("NFC", s)


class Uploader:
    def __init__(self, drive, folder_id, work="/content/work"):
        self.drive, self.root = drive, folder_id
        self.work = pathlib.Path(work)
        self.work.mkdir(parents=True, exist_ok=True)
        self.cache = {}
        self.stats = {"uploaded": 0, "skipped": 0, "bytes": 0}

    # ---- Drive helpers
    def _retry(self, fn):
        from googleapiclient.errors import HttpError
        for i in range(8):
            try:
                return fn()
            except HttpError as e:
                if e.resp.status not in (403, 429, 500, 502, 503, 504) or i == 7:
                    raise
            except (ConnectionError, socket.timeout, TimeoutError, OSError):
                if i == 7:
                    raise
            time.sleep(min(60, 2 ** i))

    def children(self, parent):
        if parent not in self.cache:
            items, tok = {}, None
            while True:
                r = self._retry(lambda: self.drive.files().list(
                    q=f"'{parent}' in parents and trashed=false", pageSize=1000, pageToken=tok,
                    fields="nextPageToken, files(id,name,mimeType,size)",
                    supportsAllDrives=True, includeItemsFromAllDrives=True).execute())
                for f in r.get("files", []):
                    items[NFC(f["name"])] = f
                tok = r.get("nextPageToken")
                if not tok:
                    break
            self.cache[parent] = items
        return self.cache[parent]

    def folder(self, parts):
        pid = self.root
        for name in parts:
            c = self.children(pid)
            if name in c and c[name]["mimeType"] == FOLDER:
                pid = c[name]["id"]
                continue
            f = self._retry(lambda: self.drive.files().create(
                body={"name": name, "mimeType": FOLDER, "parents": [pid]},
                fields="id,name,mimeType", supportsAllDrives=True).execute())
            c[name] = f
            self.cache[f["id"]] = {}
            pid = f["id"]
        return pid

    def upload(self, local, parts, mime):
        from googleapiclient.http import MediaFileUpload
        parent, name = self.folder(parts[:-1]), parts[-1]
        size = os.path.getsize(local)
        have = self.children(parent).get(name)
        if have and int(have.get("size", -1)) == size:
            self.stats["skipped"] += 1
            return "skipped"
        media = MediaFileUpload(local, mimetype=mime, chunksize=32 * 1024 * 1024, resumable=True)
        req = self.drive.files().create(body={"name": name, "parents": [parent]}, media_body=media,
                                        fields="id,name,size,mimeType", supportsAllDrives=True)
        resp = None
        while resp is None:
            _, resp = self._retry(req.next_chunk)
        self.children(parent)[name] = resp
        self.stats["uploaded"] += 1
        self.stats["bytes"] += size
        return "uploaded"

    # ---- GitHub release -> Drive
    def fetch(self, url, dest):
        for i in range(6):
            try:
                with requests.get(url, stream=True, timeout=(30, 300)) as r:
                    r.raise_for_status()
                    with open(dest, "wb") as fh:
                        for chunk in r.iter_content(8 << 20):
                            fh.write(chunk)
                return dest
            except Exception as e:
                print(f"   download retry {i + 1}: {e}")
                time.sleep(10 * (i + 1))
        raise RuntimeError(f"could not download {url}")

    def run(self, repo, tag, also_zips=False, only=None):
        rel = requests.get(f"https://api.github.com/repos/{repo}/releases/tags/{tag}", timeout=60).json()
        assets = sorted(rel["assets"], key=lambda a: a["name"])
        if only:
            assets = [a for a in assets if a["name"] in only]
        t0 = time.time()
        for a in assets:
            name, url = a["name"], a["browser_download_url"]
            local = self.work / name
            if not name.endswith(".zip"):  # INDEX.csv, README.txt -> top of the folder
                self.fetch(url, local)
                mime = "text/csv" if name.endswith(".csv") else "text/plain"
                print(f"{name}: {self.upload(local, [name], mime)}")
                local.unlink()
                continue
            print(f"\n== {name} ({a['size'] / 1e9:.2f} GB)")
            self.fetch(url, local)
            with zipfile.ZipFile(local) as z:
                members = [m for m in z.infolist() if not m.is_dir()]
                for i, m in enumerate(members, 1):
                    rel_path = NFC(m.filename)
                    if rel_path.startswith(ROOT_PREFIX):
                        rel_path = rel_path[len(ROOT_PREFIX):]
                    parts = [p for p in rel_path.split("/") if p]
                    tmp = self.work / "current.bin"
                    with z.open(m) as src, open(tmp, "wb") as dst:
                        while True:
                            b = src.read(8 << 20)
                            if not b:
                                break
                            dst.write(b)
                    mime = "application/pdf" if parts[-1].lower().endswith(".pdf") else "text/plain"
                    res = self.upload(tmp, parts, mime)
                    tmp.unlink()
                    print(f"   [{i}/{len(members)}] {res:8} {'/'.join(parts)[-110:]}")
            if also_zips:
                print(f"   zip itself: {self.upload(local, ['_zips', name], 'application/zip')}")
            local.unlink()
            el = time.time() - t0
            print(f"   done. so far: {self.stats['uploaded']} uploaded, {self.stats['skipped']} already there, "
                  f"{self.stats['bytes'] / 1e9:.1f} GB in {el / 60:.0f} min")
        print("\nALL DONE:", self.stats)
