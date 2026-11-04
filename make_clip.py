"""Makes the next 1-minute part for مصنع الكليبينق (runs on GitHub Actions).

1. Asks n8n which part is next (N8N_NEXT_URL).
2. Downloads only that minute from YouTube, puts it on a 1080x1920 black frame,
   adds the watermark top-right of the video, a title above it and Arabic captions.
3. Uploads the MP4 to this repo's "clips" release and sends the link to n8n (N8N_READY_URL).
Set DRY_RUN=1 to make Part 1 of episode 1 without talking to n8n.
"""
import json, os, subprocess, sys, time, urllib.request, uuid

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


UA = ["-user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"]


def http_json(url, data=None):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json", "User-Agent": "clip-factory"},
                                 method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read().decode() or "{}"
    return json.loads(body)


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
    return text.replace("{", "").replace("}", "").replace("\n", " ").strip()


def build_ass(title, words, video_h, length):
    top = (1920 - video_h) // 2
    out = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Title,Noto Sans Arabic,60,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,8,60,60,%d,1" % max(40, top - 150),
        "Style: Cap,Noto Sans Arabic,64,&H00FFFFFF,&H0000D4FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,4,0,2,60,60,%d,1" % max(120, top - 220),
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if title:
        out.append("Dialogue: 0,%s,%s,Title,,0,0,0,,%s" % (ass_time(0), ass_time(length), clean(title)))
    group = []
    for w in words + [None]:
        if w is not None:
            group.append(w)
        if group and (w is None or len(group) >= 5 or group[-1]["end"] - group[0]["start"] > 2.5):
            out.append("Dialogue: 0,%s,%s,Cap,,0,0,0,,%s" % (
                ass_time(group[0]["start"]), ass_time(group[-1]["end"] + 0.1), " ".join(clean(g["word"]) for g in group)))
            group = []
    return "\n".join(out) + "\n"


def main():
    if DRY:
        job = {"ep": 0, "part": 2, "part_seconds": 60,
               "source": "https://drive.usercontent.google.com/download?id=1xZeg96A4BnfULVC9KRWVPcjOyXJyDfL3&export=download&confirm=t",
               "title": "المستثمر الإماراتي | مقابلات - الجزء 3",
               "watermark_url": "https://drive.usercontent.google.com/download?id=1E36oS56HOOo9f1Xb-aSUdQhCisjLb67v&export=download&confirm=t",
               "captions": True}
    else:
        job = http_json(NEXT_URL)
    print("job:", json.dumps(job, ensure_ascii=False), flush=True)
    if not job.get("source"):
        print("nothing to do")
        return

    src, part, seg = job["source"], int(job["part"]), float(job.get("part_seconds", 60))
    youtube = "youtu" in src
    if youtube:
        total = float(run(ytdlp() + ["--print", "duration", src], 300).strip().splitlines()[-1])
    else:  # direct link (Google Drive): ffmpeg reads only the bytes it needs
        total = float(run(["ffprobe", "-v", "error"] + UA + ["-show_entries", "format=duration", "-of", "csv=p=0", src], 300, tries=5).strip())
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
        req = urllib.request.Request(job["watermark_url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r, open(wm, "wb") as f:
            f.write(r.read())

    probe = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", raw]))
    sw, sh = probe["streams"][0]["width"], probe["streams"][0]["height"]
    vh = min(1920, int(round(1080 * sh / sw / 2)) * 2)

    words = []
    if job.get("captions", True):
        from faster_whisper import WhisperModel
        model = WhisperModel("small", device="cpu", compute_type="int8", download_root=os.path.expanduser("~/.cache/whisper"))
        segments, _ = model.transcribe(raw, language="ar", word_timestamps=True, vad_filter=True)
        for s in segments:
            for w in s.words or []:
                if w.word.strip():
                    words.append({"word": w.word.strip(), "start": w.start, "end": w.end})
    ass = os.path.join(WORK, "subs.ass")
    with open(ass, "w", encoding="utf-8") as f:
        f.write(build_ass(job.get("title", ""), words, vh, length))

    name = "ep%02d-part%03d-%s.mp4" % (int(job["ep"]) + 1, part + 1, uuid.uuid4().hex[:6])
    out = os.path.join(WORK, name)
    fc = "[0:v]scale=1080:%d,setsar=1[vid];color=c=black:s=1080x1920:r=30[bg];[bg][vid]overlay=0:(H-h)/2:shortest=1[base]" % vh
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
        http_json(READY_URL, result)


if __name__ == "__main__":
    main()
