from __future__ import annotations
import os
import subprocess
import threading
import secrets
import logging
import shutil
import ipaddress
import socket
from urllib.parse import urlsplit, parse_qs
import httpx
import uuid
from pathlib import Path
from fastapi import FastAPI, File, HTTPException, UploadFile, Header, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

ROOT = Path(os.environ.get("CLIPPER_DATA_DIR", "./clipper-data")).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
MAX_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(2 * 1024**3)))
jobs: dict[str, dict] = {}
lock = threading.Lock()
MAX_ACTIVE_JOBS = max(1, int(os.environ.get("MAX_ACTIVE_JOBS", "1")))
logger = logging.getLogger(__name__)
API_TOKEN = os.environ.get('CLIPPER_API_TOKEN', '')
app = FastAPI(title="AI Clips Maker API")
origins = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET","POST"], allow_headers=["*"])


# Recover completed jobs after a single-worker restart; interrupted jobs cannot resume.
import json
import time

def persist_job(job_id: str):
    job = jobs[job_id]
    folder = ROOT / job_id
    if not folder.is_dir():
        return
    target = folder / "job.json"
    temporary = folder / "job.json.tmp"
    temporary.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)

JOB_RETENTION_HOURS = max(1, int(os.environ.get("JOB_RETENTION_HOURS", "24")))

def cleanup_expired_jobs(now: float | None = None):
    """Delete only terminal jobs older than the configured retention window."""
    cutoff = (time.time() if now is None else now) - JOB_RETENTION_HOURS * 3600
    with lock:
        expired = [
            job_id for job_id, record in jobs.items()
            if record.get("status") in ("complete", "failed")
            and (ROOT / job_id / "job.json").is_file()
            and (ROOT / job_id / "job.json").stat().st_mtime < cutoff
        ]
        for job_id in expired:
            jobs.pop(job_id, None)
    for job_id in expired:
        shutil.rmtree(ROOT / job_id, ignore_errors=True)
    return len(expired)

def recover_jobs():
    for metadata in ROOT.glob("*/job.json"):
        try:
            record = json.loads(metadata.read_text(encoding="utf-8"))
            job_id = metadata.parent.name
            if len(job_id) != 32 or not all(c in "0123456789abcdef" for c in job_id):
                continue
            if record.get("id") != job_id:
                continue
            if record.get("status") not in ("complete", "failed"):
                record["status"] = "failed"
                record["error"] = "Processing interrupted by server restart. Submit the video again."
                record["outputs"] = []
            jobs[job_id] = record
            persist_job(job_id)
        except (OSError, ValueError, TypeError):
            logger.warning("Skipping invalid job metadata at %s", metadata)

recover_jobs()
cleanup_expired_jobs()

def probe(path: Path) -> float:
    result = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],capture_output=True,text=True,check=True,timeout=30)
    duration = float(result.stdout.strip())
    if not 0 < duration <= 4 * 3600:
        raise ValueError("Video must be between 0 and 4 hours")
    return duration

def srt_time(seconds: float) -> str:
    millis = round(max(0,seconds)*1000)
    h,rem=divmod(millis,3600000)
    m,rem=divmod(rem,60000)
    s,ms=divmod(rem,1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def transcribe(path: Path):
    from faster_whisper import WhisperModel
    model = WhisperModel(os.environ.get("WHISPER_MODEL","small"), device="cpu", compute_type="int8")
    segments,_ = model.transcribe(str(path),language=os.environ.get("TRANSCRIPTION_LANGUAGE") or None,vad_filter=True,beam_size=3)
    return [{"start":float(s.start),"end":float(s.end),"text":s.text.strip()} for s in segments if s.text.strip()]

def windows(segments, duration, length, limit=3):
    if duration < length or limit <= 0:
        return []
    # Speech-density baseline, not semantic highlight ranking.
    step = max(15, length // 2)
    last_start = max(0, int(duration - length))
    starts = sorted(set(range(0, last_start + 1, step)) | {last_start})
    candidates = []
    for start in starts:
        end = start + length
        score = sum(max(0, min(end, s["end"]) - max(start, s["start"])) for s in segments)
        candidates.append((score, start))
    # Do not create random silent clips if speech is absent.
    if not segments:
        return [0] if last_start == 0 else []
    candidates.sort(key=lambda item: (-item[0], item[1]))
    chosen = []
    for score, start in candidates:
        if score <= 0:
            break
        if all(abs(start - previous) >= length for previous in chosen):
            chosen.append(start)
        if len(chosen) >= limit:
            break
    return sorted(chosen)

def render(source:Path,target:Path,start:int,length:int,vertical:bool,subtitles:Path):
    vf=("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920" if vertical else "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2")
    # Relative subtitle filename avoids unsafe interpolation of user-supplied paths.
    # FFmpeg must be built with libass for the subtitles filter.
    vf += ",subtitles=" + subtitles.name
    subprocess.run(["ffmpeg","-nostdin","-y","-ss",str(start),"-i",str(source),"-t",str(length),"-vf",vf,"-c:v","libx264","-preset","veryfast","-crf","24","-c:a","aac","-movflags","+faststart",str(target)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=7200,cwd=str(source.parent))

def check_token(authorization: str | None):
    if API_TOKEN and not secrets.compare_digest(authorization or '', 'Bearer '+API_TOKEN):
        raise HTTPException(401, 'Unauthorized')

def process(job_id:str,source:Path,lengths:tuple[int,...]):
    try:
        jobs[job_id]["status"]="transcribing"
        duration=probe(source)
        segments=transcribe(source)
        if not segments:
            raise ValueError("No speech detected in the source video")
        jobs[job_id]["status"]="rendering"
        outputs=[]
        folder=source.parent
        for length in lengths:
            for idx,start in enumerate(windows(segments,duration,length),1):
                subset=[s for s in segments if s["end"]>start and s["start"]<start+length]
                name=f"{length}s_{idx}"
                srt=folder/f"{name}.srt"
                with srt.open("w",encoding="utf-8") as f:
                    for n,s in enumerate(subset,1):
                        a=max(0,s["start"]-start); b=min(length,s["end"]-start)
                        f.write(f"{n}\n{srt_time(a)} --> {srt_time(b)}\n{s['text']}\n\n")
                for vertical in (True,False):
                    aspect="vertical" if vertical else "landscape"
                    target=folder/f"{name}_{aspect}.mp4"
                    render(source,target,start,length,vertical,srt)
                    outputs.append({"name":target.name,"duration":length,"start":start,"aspect":aspect,"video":f"/api/jobs/{job_id}/files/{target.name}","srt":f"/api/jobs/{job_id}/files/{srt.name}"})
        if not outputs:
            raise ValueError("No suitable speech-containing windows for selected clip lengths")
        # Imported source is no longer needed once rendered outputs are ready.
        source.unlink(missing_ok=True)
        jobs[job_id].update(status="complete",outputs=outputs,transcript_segments=len(segments))
        persist_job(job_id)
    except Exception:
        logger.exception("Processing failed for job %s", job_id)
        shutil.rmtree(source.parent, ignore_errors=True)
        jobs[job_id].update(status="failed",error="Processing failed. Check server logs for details.")

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.get("/api/ready")
def ready(authorization: str | None = Header(default=None)):
    check_token(authorization)
    dependencies = {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
    }
    storage = ROOT.is_dir() and os.access(ROOT, os.W_OK | os.X_OK)
    if not all(dependencies.values()) or not storage:
        raise HTTPException(503, detail={"dependencies": dependencies, "storage_writable": storage})
    return {"status": "ready", "dependencies": dependencies, "storage_writable": storage}

@app.post("/api/jobs",status_code=202)
async def create_job(file:UploadFile=File(...), lengths: str=Form(default='30,60'), authorization: str | None=Header(default=None)):
    check_token(authorization)
    try:
        chosen = tuple(sorted(set(int(x.strip()) for x in lengths.split(','))))
    except ValueError:
        raise HTTPException(422, "Invalid clip lengths")
    if not chosen or any(x not in (30, 60, 1800) for x in chosen):
        raise HTTPException(422, "Choose one or more lengths: 30, 60, 1800")
    if file.content_type not in ("video/mp4","video/quicktime","application/octet-stream"):
        raise HTTPException(415,"Upload MP4 or MOV")
    job_id=uuid.uuid4().hex
    folder=ROOT/job_id
    with lock:
        active = sum(j["status"] not in ("complete", "failed") for j in jobs.values())
        if active >= MAX_ACTIVE_JOBS:
            raise HTTPException(429, "Processing capacity reached. Retry later.")
        jobs[job_id]={"id":job_id,"status":"uploading","outputs":[],"lengths":list(chosen)}
    try:
        folder.mkdir()
    except Exception:
        with lock:
            jobs.pop(job_id, None)
        raise
    source=folder/("source.mov" if file.filename and file.filename.lower().endswith(".mov") else "source.mp4")
    size=0
    try:
        with source.open("wb") as output:
            while chunk:=await file.read(1024*1024):
                size+=len(chunk)
                if size>MAX_BYTES: raise HTTPException(413,"File exceeds upload limit")
                output.write(chunk)
        if not size: raise HTTPException(400,"Empty upload")
    except Exception:
        source.unlink(missing_ok=True)
        shutil.rmtree(folder, ignore_errors=True)
        with lock:
            jobs.pop(job_id, None)
        raise
    jobs[job_id]["status"]="queued"
    persist_job(job_id)
    threading.Thread(target=process,args=(job_id,source,chosen),daemon=True).start()
    return jobs[job_id]


def is_youtube_url(value: str) -> bool:
    """Accept only a single HTTPS YouTube video, never playlists or channel URLs."""
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
            return False
        host = (parsed.hostname or "").lower()
        if host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
            return False
        if host == "youtu.be":
            video_id = parsed.path.strip("/")
            return bool(video_id) and "/" not in video_id and len(video_id) == 11 and video_id.replace("-", "").replace("_", "").isalnum()
        if parsed.path == "/watch":
            query = parse_qs(parsed.query)
            video_id = query.get("v", [""])[0]
            return len(video_id) == 11 and video_id.replace("-", "").replace("_", "").isalnum() and "list" not in query
        if parsed.path.startswith("/shorts/") or parsed.path.startswith("/live/"):
            video_id = parsed.path.split("/")
            return len(video_id) == 3 and len(video_id[2]) == 11 and video_id[2].replace("-", "").replace("_", "").isalnum()
        return False
    except ValueError:
        return False

def canonical_youtube_url(value: str) -> str:
    """Discard arbitrary query parameters and force one canonical video URL."""
    if not is_youtube_url(value):
        raise ValueError("Invalid individual YouTube video URL")
    parsed = urlsplit(value.strip())
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        video_id = parsed.path.strip("/")
    elif parsed.path == "/watch":
        video_id = parse_qs(parsed.query)["v"][0]
    else:
        video_id = parsed.path.split("/")[2]
    return "https://www.youtube.com/watch?v=" + video_id

def validate_source_url(value: str) -> str:
    """Only HTTPS direct-media URLs on explicitly trusted hosts."""
    url = urlsplit(value.strip())
    allowed = {x.strip().lower() for x in os.environ.get("DIRECT_VIDEO_HOSTS", "").split(",") if x.strip()}
    hostname = (url.hostname or "").lower()
    if url.scheme != "https" or not hostname or hostname not in allowed or url.username or url.password or url.port not in (None, 443):
        raise HTTPException(422, "Only HTTPS direct-video links from configured trusted hosts are supported")
    try:
        addresses = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError("Non-public address")
    except (OSError, ValueError):
        raise HTTPException(422, "Video host could not be validated")
    return value.strip()

def import_direct_video(url: str, destination: Path):
    # No redirects: prevents untrusted destination hops.
    with httpx.Client(follow_redirects=False, timeout=httpx.Timeout(30, read=120), trust_env=False) as client:
        with client.stream("GET", url, headers={"Accept": "video/*"}) as response:
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError("Direct media URL did not return a video")
            mime = response.headers.get("content-type", "").split(";")[0].lower()
            if mime not in ("video/mp4", "video/quicktime", "application/octet-stream"):
                raise ValueError("Link is not a direct MP4/MOV media file")
            total = 0
            with destination.open("wb") as output:
                for chunk in response.iter_bytes(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise ValueError("Linked video exceeds size limit")
                    output.write(chunk)
            if not total:
                raise ValueError("Empty linked video")

def import_youtube_video(url: str, destination: Path):
    """Best-effort import of publicly accessible videos, without login or DRM bypass."""
    from yt_dlp import YoutubeDL
    if not is_youtube_url(url):
        raise ValueError("Unsupported YouTube URL")
    options = {
        "format": "best[ext=mp4][height<=720]/best[ext=mp4]",
        "outtmpl": str(destination.with_suffix(".%(ext)s")),
        "noplaylist": True,
        "max_filesize": MAX_BYTES,
        "socket_timeout": 30,
        "retries": 2,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "extract_flat": False,
        "skip_download": False,
        "restrictfilenames": True,
        "windowsfilenames": True,
    }
    canonical_url = canonical_youtube_url(url)
    with YoutubeDL(options) as downloader:
        metadata = downloader.extract_info(canonical_url, download=False)
        if not metadata or metadata.get("_type") == "playlist" or metadata.get("duration") is None or metadata["duration"] > 4 * 3600:
            raise ValueError("Video unavailable or exceeds four hours")
        downloader.download([canonical_url])
    candidates = [p for p in destination.parent.glob("source.*") if p.is_file()]
    if len(candidates) != 1 or candidates[0].stat().st_size > MAX_BYTES:
        raise ValueError("Video import exceeded limits or produced unexpected files")
    if candidates[0].suffix.lower() != ".mp4":
        raise ValueError("Source must be an MP4")
    if candidates[0] != destination:
        candidates[0].rename(destination)

def process_link(job_id: str, url: str, lengths: tuple[int, ...]):
    source = ROOT / job_id / "source.mp4"
    try:
        jobs[job_id]["status"] = "importing"
        if is_youtube_url(url):
            import_youtube_video(url, source)
        else:
            import_direct_video(url, source)
        process(job_id, source, lengths)
    except Exception:
        logger.exception("Link import failed for job %s", job_id)
        shutil.rmtree(ROOT / job_id, ignore_errors=True)
        jobs[job_id].update(status="failed", error="Video import failed. Verify the video link and server configuration.")

@app.post("/api/jobs/from-link", status_code=202)
def create_link_job(url: str = Form(...), lengths: str = Form(default="30,60"), authorization: str | None = Header(default=None)):
    check_token(authorization)
    validated = url.strip() if is_youtube_url(url) else validate_source_url(url)
    try:
        chosen = tuple(sorted(set(int(x.strip()) for x in lengths.split(","))))
    except ValueError:
        raise HTTPException(422, "Invalid clip lengths")
    if not chosen or any(x not in (30, 60, 1800) for x in chosen):
        raise HTTPException(422, "Choose one or more lengths: 30, 60, 1800")
    job_id = uuid.uuid4().hex
    with lock:
        if sum(j["status"] not in ("complete", "failed") for j in jobs.values()) >= MAX_ACTIVE_JOBS:
            raise HTTPException(429, "Processing capacity reached. Retry later.")
        jobs[job_id] = {"id": job_id, "status": "queued", "outputs": [], "lengths": list(chosen)}
    try:
        (ROOT / job_id).mkdir()
        persist_job(job_id)
        threading.Thread(target=process_link, args=(job_id, validated, chosen), daemon=True).start()
    except Exception:
        with lock:
            jobs.pop(job_id, None)
        shutil.rmtree(ROOT / job_id, ignore_errors=True)
        raise
    return jobs[job_id]

@app.get("/api/jobs/{job_id}")
def get_job(job_id:str, authorization: str | None=Header(default=None)):
    check_token(authorization)
    if job_id not in jobs: raise HTTPException(404,"Job not found")
    return jobs[job_id]

@app.get("/api/jobs/{job_id}/files/{filename}")
def get_file(job_id:str,filename:str, authorization: str | None=Header(default=None)):
    check_token(authorization)
    if job_id not in jobs or jobs[job_id]["status"] != "complete" or filename!=Path(filename).name or not (filename.endswith('.mp4') or filename.endswith('.srt')):
        raise HTTPException(404,"File not found")
    allowed = {Path(o["name"]).name for o in jobs[job_id].get("outputs", [])}
    allowed.update(Path(o["srt"]).name for o in jobs[job_id].get("outputs", []))
    if filename not in allowed:
        raise HTTPException(404,"File not found")
    path=ROOT/job_id/filename
    if not path.is_file(): raise HTTPException(404,"File not found")
    return FileResponse(path,filename=filename)
