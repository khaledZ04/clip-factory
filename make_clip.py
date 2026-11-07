"""Makes the next 1-minute part for مصنع الكليبينق (runs on GitHub Actions).

1. Asks n8n which part is next (N8N_NEXT_URL).
2. Downloads only that minute from YouTube, puts it on a 1080x1920 black frame,
   adds the watermark top-right of the video, a title above it and Arabic captions.
3. Uploads the MP4 to this repo's "clips" release and sends the link to n8n (N8N_READY_URL).
Set DRY_RUN=1 to make Part 1 of episode 1 without talking to n8n.
"""
import json, os, subprocess, sys, time, urllib.parse, urllib.request, uuid

NEXT_URL = os.environ.get("N8N_NEXT_URL", "")
READY_URL = os.environ.get("N8N_READY_URL", "")
COOKIES = os.environ.get("YT_COOKIES", "")
DRY = os.environ.get("DRY_RUN") == "1"
REPO = os.environ.get("GITHUB_REPOSITORY", "")
WORK = "work"
os.makedirs(WORK, exist_ok=True)


def run(cmd, timeout=1500, tries=1):
    for attempt in range(tries):
        print("+", " ".join(cmd[:6]), flush=True)
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if p.returncode == 0:
            return p.stdout
        print(p.stderr[-3000:], flush=True)
        if attempt < tries - 1:
            print("retrying in 45s (Drive sometimes refuses for a moment)", flush=True)
            time.sleep(45)
    raise SystemExit(cmd[0] + " failed")


UA_STR = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
UA = ["-user_agent", UA_STR]


CHUNK = 8 * 1024 * 1024


def drive_relay(src):
    """Drive refuses open-ended downloads of busy shared files ("Quota exceeded") but still
    answers fixed-size slices. This local relay turns ffmpeg's requests into 8 MB slices."""
    import http.server, re, threading

    file_id = urllib.parse.parse_qs(urllib.parse.urlparse(src).query).get("id", [""])[0]
    mirrors = [src, "https://drive.google.com/uc?export=download&confirm=t&id=" + file_id] if file_id else [src]

    def fetch(a, b):
        # Drive refuses some slices for a while; keep trying (about 10 minutes) on both Drive hosts
        for attempt in range(24):
            url = mirrors[attempt % len(mirrors)]
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA_STR, "Range": "bytes=%d-%d" % (a, b)})
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = r.read()
                    if r.status == 206 and len(data) == b - a + 1:
                        return data, r.headers.get("Content-Range", "")
                    raise IOError("Drive answered %s %s" % (r.status, r.headers.get("Content-Type")))
            except Exception as e:
                print("slice %d-%d refused (%s), retry %d" % (a, b, str(e)[:60], attempt + 1), flush=True)
                time.sleep(min(60, 5 + attempt * 5))
        raise IOError("Drive kept refusing")

    total = int(fetch(0, 1023)[1].split("/")[-1])

    class Relay(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "bytes=0-"))
            a = int(m.group(1) or 0)
            b = int(m.group(2)) if m.group(2) else total - 1
            self.send_response(206)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", "bytes %d-%d/%d" % (a, b, total))
            self.send_header("Content-Length", str(b - a + 1))
            self.end_headers()
            try:
                pos = a
                while pos <= b:
                    end = min(b, pos + CHUNK - 1)
                    self.wfile.write(fetch(pos, end)[0])
                    pos = end + 1
            except (BrokenPipeError, ConnectionResetError):
                pass  # ffmpeg jumped elsewhere

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Relay)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return "http://127.0.0.1:%d/video.mp4" % srv.server_address[1]


def resolve_drive(src):
    """Drive sometimes answers with a 'can't scan for viruses' page instead of the video.
    Read that page and build the real download link (same trick gdown uses)."""
    import html, re
    for attempt in range(5):
        req = urllib.request.Request(src, headers={"User-Agent": UA_STR, "Range": "bytes=0-2047"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                ctype = r.headers.get("Content-Type", "")
                body = r.read()
        except Exception as e:
            print("drive check error:", e, flush=True)
            time.sleep(45)
            continue
        if not ctype.startswith("text/html"):
            return src
        page = body.decode("utf-8", "ignore")
        title = re.search(r"<title>(.*?)</title>", page, re.S)
        print("drive answered a page:", title.group(1).strip() if title else page[:200], flush=True)
        fields = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', page))
        if "id" in fields and "uuid" in fields:
            src = "https://drive.usercontent.google.com/download?" + "&".join(
                "%s=%s" % (k, urllib.parse.quote(html.unescape(v))) for k, v in fields.items())
            continue  # check the new link too
        time.sleep(45)
    return src


def http_json(url, data=None):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json", "User-Agent": "clip-factory"},
                                 method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read().decode() or "{}"
    return json.loads(body)


def tiktok_upload(path, title):
    """Asks n8n for a one-time TikTok upload link and sends the file straight to TikTok.
    (n8n is too small to hold the video in memory.) Returns the publish_id, or None to skip TikTok."""
    try:
        size = os.path.getsize(path)
        base = NEXT_URL.split("?")[0].replace("clip-next-", "tiktok-upload-")
        info = http_json(base + "?" + urllib.parse.urlencode({"size": size, "title": title}))
        if not info.get("upload_url"):
            print("tiktok: skipped -", info.get("reason", info), flush=True)
            return None
        chunk, count = int(info["chunk_size"]), int(info["chunk_count"])
        with open(path, "rb") as f:
            for i in range(count):
                start = i * chunk
                end = size - 1 if i == count - 1 else start + chunk - 1
                f.seek(start)
                data = f.read(end - start + 1)
                req = urllib.request.Request(info["upload_url"], data=data, method="PUT", headers={
                    "Content-Type": "video/mp4", "Content-Length": str(len(data)),
                    "Content-Range": "bytes %d-%d/%d" % (start, end, size)})
                with urllib.request.urlopen(req, timeout=600) as r:
                    r.read()
        print("tiktok: uploaded %d bytes in %d chunk(s)" % (size, count), flush=True)
        return info["publish_id"]
    except Exception as e:
        print("tiktok: upload failed -", str(e)[:300], flush=True)
        return None


def tiktok_web_post(path, job):
    """Posts on TikTok through TikTok Studio on the web (tiktok-post.js). Returns the video link or None."""
    cap = os.path.join(WORK, "tiktok-caption.txt")
    with open(cap, "w", encoding="utf-8") as f:
        f.write(job.get("tiktok_caption") or job.get("title", ""))
    handle = job.get("tiktok_handle") or "jancostudios"
    try:
        p = subprocess.run(["node", "tiktok-post.js", path, cap, handle], capture_output=True, text=True, timeout=1500)
    except subprocess.TimeoutExpired:
        notify("TikTok bot timed out - post this clip by hand", job.get("title", ""))
        return None
    out = p.stdout + p.stderr
    print(out[-2000:], flush=True)
    for line in out.splitlines():
        if line.startswith("tiktok_url: "):
            return line.split(": ", 1)[1].strip()
    if p.returncode == 2:
        notify("TikTok sign-in expired - post by hand", "Run save-tiktok-login.js again.\n" + job.get("title", ""))
    elif p.returncode == 3:
        notify("TikTok asked for a puzzle - post this clip by hand", job.get("title", ""))
    elif p.returncode == 4:
        notify("TikTok: posted, but no link yet - submit by hand", job.get("title", ""), "https://www.tiktok.com/@" + handle)
        return "POSTED_NO_LINK"
    else:
        notify("TikTok bot failed - post this clip by hand", job.get("title", "") + "\n" + out[-300:])
    return None


def ytdlp():
    cmd = ["yt-dlp", "--no-playlist", "--no-warnings"]
    if COOKIES:
        with open("cookies.txt", "w") as f:
            f.write(COOKIES)
        cmd += ["--cookies", "cookies.txt"]
    return cmd


def ass_time(t):
    h, rem = divmod(max(0.0, t), 3600)
    m, s = divmod(rem, 60)
    return "%d:%02d:%05.2f" % (h, m, s)


def clean(text):
    text = text.replace("{", "").replace("}", "").replace("\n", " ")
    # captions read cleaner without punctuation (it also jumps to the wrong side in right-to-left lines)
    return text.strip(" .,،؛:!?؟…\"'«»-")


# colours are &HBBGGRR (ASS order)
GOLD, RED, YELLOW, WHITE, DARK = "&H0000C3FF", "&H004639E6", "&H0000E6FF", "&H00FFFFFF", "&H00141414"


def build_ass(title, words, video_h, length):
    top = (1920 - video_h) // 2
    bottom = top + video_h
    out = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        # gold box with dark text (BorderStyle 3 = box in OutlineColour)
        "Style: Title,Tajawal ExtraBold,62,%s,%s,%s,&H00000000,0,0,0,0,100,100,0,0,3,18,0,8,40,40,0,1" % (DARK, DARK, GOLD),
        # red badge with white text
        "Style: Badge,Tajawal ExtraBold,52,%s,%s,%s,&H00000000,0,0,0,0,100,100,0,0,3,14,0,8,40,40,0,1" % (WHITE, WHITE, RED),
        # big white captions, thick black outline, soft shadow
        "Style: Cap,Almarai ExtraBold,96,%s,%s,&H00000000,&H90000000,0,0,0,0,100,100,0,0,1,8,4,8,40,40,0,1" % (WHITE, WHITE),
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if title:
        name, _, badge = title.rpartition(" - ")
        if not name:
            name, badge = title, ""
        out.append("Dialogue: 1,%s,%s,Title,,0,0,0,,{\\an8\\pos(540,%d)\\fad(300,0)}%s" % (ass_time(0), ass_time(length), max(30, top - 230), clean(name)))
        if badge:
            out.append("Dialogue: 1,%s,%s,Badge,,0,0,0,,{\\an8\\pos(540,%d)\\fad(300,0)}%s" % (ass_time(0), ass_time(length), max(120, top - 120), clean(badge)))

    # captions: up to 4 words per line, the word being spoken turns yellow and pops a little
    groups, group = [], []
    for w in words:
        if group and (len(group) >= 3 or w["start"] - group[-1]["end"] > 0.8 or w["end"] - group[0]["start"] > 2.2):
            groups.append(group)
            group = []
        group.append(w)
    if group:
        groups.append(group)
    pos = "{\\an8\\pos(540,%d)}" % min(1700, bottom + 70)
    for gi, g in enumerate(groups):
        line_end = min(g[-1]["end"] + 0.25, groups[gi + 1][0]["start"] if gi + 1 < len(groups) else length)
        for i, w in enumerate(g):
            s = g[0]["start"] if i == 0 else w["start"]
            e = g[i + 1]["start"] if i + 1 < len(g) else line_end
            if e <= s:
                continue
            # The renderer lays out each styled piece left-to-right, so pieces go in visual order:
            # words after the spoken one (left), the spoken word, words before it (right) -> reads right-to-left.
            before = " ".join(clean(x["word"]) for x in g[:i])
            after = " ".join(clean(x["word"]) for x in g[i + 1:])
            # spoken word: dark text on a big yellow highlight (thick yellow outline acts as the box)
            active = "{\\c%s\\3c%s\\bord15\\shad0\\fscx112\\fscy112}%s{\\r}" % (DARK, YELLOW, clean(w["word"]))
            text = "  ".join(p for p in (after, active, before) if p)  # wide gaps so the highlight never covers a neighbour
            out.append("Dialogue: 0,%s,%s,Cap,,0,0,0,,%s%s" % (ass_time(s), ass_time(e), pos, text))
    return "\n".join(out) + "\n"


def main():
    if DRY:
        tf = os.environ.get("TEST_FILE") or "1xZeg96A4BnfULVC9KRWVPcjOyXJyDfL3"
        job = {"ep": 0, "part": int(os.environ.get("TEST_PART") or 2), "part_seconds": 60,
               "source": "https://drive.usercontent.google.com/download?id=" + tf + "&export=download&confirm=t",
               "title": "المستثمر الإماراتي | تجربة - الجزء %d" % (int(os.environ.get("TEST_PART") or 2) + 1),
               "watermark_url": "https://drive.usercontent.google.com/download?id=1E36oS56HOOo9f1Xb-aSUdQhCisjLb67v&export=download&confirm=t",
               "captions": True}
    else:
        job = http_json(NEXT_URL + "?trigger=" + os.environ.get("GITHUB_EVENT_NAME", "manual"))
    print("job:", json.dumps(job, ensure_ascii=False), flush=True)
    if not job.get("source"):
        print("nothing to do")
        return

    src, part, seg = job["source"], int(job["part"]), float(job.get("part_seconds", 60))
    youtube = "youtu" in src
    if youtube:
        total = float(run(ytdlp() + ["--print", "duration", src], 300).strip().splitlines()[-1])
    else:  # direct link (Google Drive): ffmpeg reads only the bytes it needs
        src = drive_relay(src)
        total = float(run(["ffprobe", "-v", "error"] + UA + ["-show_entries", "format=duration", "-of", "csv=p=0", src], 1500, tries=2).strip())
    start = part * seg
    if start >= total - 15:  # under 15 s left (already glued onto the previous part)
        if not DRY:
            http_json(READY_URL, {"done": True, "ep": job["ep"], "part": part})
        print("episode finished")
        return
    length = total - start if total - (start + seg) < 15 else seg
    is_last = start + length >= total - 1

    raw = os.path.join(WORK, "raw.mp4")
    if youtube:
        run(ytdlp() + ["-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]/b",
                       "--download-sections", "*%.2f-%.2f" % (start, start + length),
                       "--force-keyframes-at-cuts", "--merge-output-format", "mp4", "-o", raw, src])
    else:
        run(["ffmpeg", "-y"] + UA + ["-ss", "%.2f" % start, "-i", src, "-t", "%.2f" % length, "-map", "0:v:0", "-map", "0:a:0?",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-c:a", "aac", "-b:a", "192k", raw], tries=3)

    wm = os.path.join(WORK, "watermark")
    if job.get("watermark_url"):
        data = b""
        try:
            req = urllib.request.Request(job["watermark_url"], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
        except Exception as e:
            print("watermark download failed:", e, flush=True)
        if not data.startswith(b"\x89PNG") and not data.startswith(b"\xff\xd8"):
            # Drive sometimes sends an HTML page instead of the image; use the copy kept in the repo
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "watermark.png"), "rb") as f:
                data = f.read()
        with open(wm, "wb") as f:
            f.write(data)

    got = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", raw]).strip() or 0)
    if got < length - 2:  # never post a cut-short clip; the same part is tried again next run
        raise SystemExit("clip came out %.1fs instead of %.1fs (Drive refused part of it)" % (got, length))
    probe = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", raw]))
    sw, sh = probe["streams"][0]["width"], probe["streams"][0]["height"]
    vh = min(1920, int(round(1080 * sh / sw / 2)) * 2)

    words = []
    if job.get("captions", True):
        from faster_whisper import WhisperModel
        model = WhisperModel(os.environ.get("WHISPER_MODEL", "large-v3-turbo"), device="cpu", compute_type="int8",
                             cpu_threads=os.cpu_count() or 4, download_root=os.path.expanduser("~/.cache/whisper"))
        segments, _ = model.transcribe(
            raw, language="ar", word_timestamps=True, vad_filter=True, beam_size=5,
            condition_on_previous_text=False,
            initial_prompt="حلقة بودكاست باللهجة الخليجية مع المستثمر الإماراتي علي الحامد، بودكاست أصولي، الاستثمار والتجارة وريادة الأعمال.")
        for s in segments:
            for w in s.words or []:
                if w.word.strip():
                    words.append({"word": w.word.strip(), "start": w.start, "end": w.end})
    ass = os.path.join(WORK, "subs.ass")
    with open(ass, "w", encoding="utf-8") as f:
        f.write(build_ass(job.get("title", ""), words, vh, length))

    name = "ep%02d-part%03d-%s.mp4" % (int(job["ep"]) + 1, part + 1, uuid.uuid4().hex[:6])
    out = os.path.join(WORK, name)
    # background = the same video, zoomed, blurred and darkened; sharp video in the middle
    fc = ("[0:v]split[a][b];"
          "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=30,eq=brightness=-0.18:saturation=1.2,setsar=1[bg];"
          "[b]scale=1080:%d,setsar=1[vid];[bg][vid]overlay=0:(H-h)/2,fps=30[base]") % vh
    inputs = ["-i", raw]
    last = "base"
    if os.path.exists(wm):
        inputs += ["-i", wm]
        fc += ";[1:v]scale=200:-1[wm];[base][wm]overlay=W-w-24:%d[wmd]" % ((1920 - vh) // 2 + 24)
        last = "wmd"
    fc += ";[%s]ass=%s[outv]" % (last, ass)
    run(["ffmpeg", "-y"] + inputs + ["-filter_complex", fc, "-map", "[outv]", "-map", "0:a?", "-t", "%.2f" % length,
         "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-c:a", "aac", "-b:a", "160k",
         "-movflags", "+faststart", out])

    run(["gh", "release", "upload", "clips", out, "--repo", REPO, "--clobber"])
    url = "https://github.com/%s/releases/download/clips/%s" % (REPO, name)
    result = {"url": url, "ep": job["ep"], "part": part, "title": job.get("title", ""), "is_last": is_last,
              "length": length, "source_duration": total, "caption_words": len(words)}
    print("result:", json.dumps(result, ensure_ascii=False), flush=True)
    if not DRY:
        web = tiktok_web_post(out, job) if os.environ.get("TT_SESSION") else None
        if web == "POSTED_NO_LINK":
            result["tiktok_posted"] = True  # it is up on TikTok; don't post this part again
        elif web:
            result["tiktok_url"] = web
        else:
            result["tiktok_publish_id"] = tiktok_upload(out, job.get("title", ""))  # fallback: draft in the TikTok inbox
        http_json(READY_URL, result)
        submit_when_posted(job["ep"], part, job.get("title", ""))


def notify(title, text, click=""):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return
    headers = {"Title": title.encode("utf-8").decode("latin-1", "ignore") or "clip", "Priority": "high",
               "Icon": "https://raw.githubusercontent.com/khaledZ04/clip-factory/main/tiktok-logo.png"}  # TikTok logo next to the alert
    if click:
        headers["Click"] = click
    try:
        urllib.request.urlopen(urllib.request.Request("https://ntfy.sh/" + topic, data=text.encode("utf-8"), headers=headers), timeout=30)
    except Exception as e:
        print("ntfy failed:", e)


def submit_when_posted(ep, part, title):
    """Waits for n8n to finish posting (up to 25 min), then submits both links on Content Rewards."""
    if not os.environ.get("CR_SESSION"):
        print("no CR_SESSION secret yet - skipping auto-submit")
        return
    links_url = READY_URL.replace("clip-ready", "clip-links") + "?key=%s-%s" % (ep, part)
    links = {}
    for _ in range(50):
        try:
            links = http_json(links_url)
        except Exception as e:
            print("links not ready:", e)
        if links.get("notPosted"):
            print("n8n posted nothing (no account connected) - nothing to submit")
            return
        if links.get("tiktokUrl") or links.get("instagramUrl"):
            break
        time.sleep(30)
    urls = [u for u in (links.get("tiktokUrl"), links.get("instagramUrl")) if u]
    if not urls:
        notify("Clip posted? no links after 25 min", title)
        return
    p = subprocess.run([sys.executable, "submit.py"] + urls, capture_output=True, text=True, timeout=900)
    print(p.stdout[-3000:], p.stderr[-3000:], flush=True)
    if "LOGIN_EXPIRED" in p.stdout + p.stderr:
        notify("Content Rewards sign-in expired - submit by hand", "Run save-login.js again.\n" + "\n".join(urls),
               "https://contentrewards.com/c/campaigns/e73e9e9c-fba4-4c8b-9c0e-6fb1e607c2a5")
    elif p.returncode == 0:
        notify("Submitted to Content Rewards", title + "\n" + "\n".join(urls), urls[0])
    else:
        notify("Auto-submit failed - submit by hand within 30 min", title + "\n" + "\n".join(urls),
               "https://contentrewards.com/c/campaigns/e73e9e9c-fba4-4c8b-9c0e-6fb1e607c2a5")


if __name__ == "__main__":
    main()
