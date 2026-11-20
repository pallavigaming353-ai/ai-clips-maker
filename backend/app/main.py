from __future__ import annotations
import os
import subprocess
import threading
import secrets
import logging
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
    segments,_ = model.transcribe(str(path),language="hi",vad_filter=True,beam_size=3)
    return [{"start":float(s.start),"end":float(s.end),"text":s.text.strip()} for s in segments if s.text.strip()]

def windows(segments, duration, length, limit=3):
    if duration < length: return []
    # Deterministic speech-density heuristic; not a semantic AI highlight score.
    candidates=[]
    step=max(15,length//2)
    for start in range(0,int(duration-length)+1,step):
        end=start+length
        score=sum(max(0,min(end,s["end"])-max(start,s["start"])) for s in segments)
        candidates.append((score,start))
    candidates.sort(reverse=True)
    chosen=[]
    for score,start in candidates:
        if all(abs(start-prev)>=length for prev in chosen):
            chosen.append(start)
        if len(chosen)>=limit: break
    return sorted(chosen)

def render(source:Path,target:Path,start:int,length:int,vertical:bool,subtitles:Path):
    vf=("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920" if vertical else "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2")
    # Relative subtitle filename avoids unsafe interpolation of user-supplied paths.
    # FFmpeg must be built with libass for the subtitles filter.
    vf += ",subtitles=" + subtitles.name + ":force_style=FontSize=20,Outline=2,Shadow=1"
    subprocess.run(["ffmpeg","-nostdin","-y","-ss",str(start),"-i",str(source),"-t",str(length),"-vf",vf,"-c:v","libx264","-preset","veryfast","-crf","24","-c:a","aac","-movflags","+faststart",str(target)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=7200,cwd=str(source.parent))

def check_token(authorization: str | None):
    if API_TOKEN and not secrets.compare_digest(authorization or '', 'Bearer '+API_TOKEN):
        raise HTTPException(401, 'Unauthorized')

def process(job_id:str,source:Path,lengths:tuple[int,...]):
    try:
        jobs[job_id]["status"]="transcribing"
        duration=probe(source)
        segments=transcribe(source)
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
        jobs[job_id].update(status="complete",outputs=outputs,transcript_segments=len(segments))
    except Exception:
        logger.exception("Processing failed for job %s", job_id)
        jobs[job_id].update(status="failed",error="Processing failed. Check server logs for details.")

@app.get("/api/health")
def health(): return {"status":"ok"}

@app.post("/api/jobs",status_code=202)
async def create_job(file:UploadFile=File(...), lengths: str=Form(default='30,60'), authorization: str | None=Header(default=None)):
    check_token(authorization)
    try:
        chosen = tuple(sorted(set(int(x.strip()) for x in lengths.split(','))))
    except ValueError:
        raise HTTPException(422, "Invalid clip lengths")
    if not chosen or any(x not in (30, 60, 1800) for x in chosen):
        raise HTTPException(422, "Choose one or more lengths: 30, 60, 1800")
    with lock:
        active = sum(j["status"] not in ("complete", "failed") for j in jobs.values())
        if active >= MAX_ACTIVE_JOBS:
            raise HTTPException(429, "Processing capacity reached. Retry later.")
    if file.content_type not in ("video/mp4","video/quicktime","application/octet-stream"):
        raise HTTPException(415,"Upload MP4 or MOV")
    job_id=uuid.uuid4().hex
    folder=ROOT/job_id
    folder.mkdir()
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
        folder.rmdir()
        raise
    with lock:
        jobs[job_id]={"id":job_id,"status":"queued","outputs":[],"lengths":list(chosen)}
    threading.Thread(target=process,args=(job_id,source,chosen),daemon=True).start()
    return jobs[job_id]

@app.get("/api/jobs/{job_id}")
def get_job(job_id:str, authorization: str | None=Header(default=None)):
    check_token(authorization)
    if job_id not in jobs: raise HTTPException(404,"Job not found")
    return jobs[job_id]

@app.get("/api/jobs/{job_id}/files/{filename}")
def get_file(job_id:str,filename:str, authorization: str | None=Header(default=None)):
    check_token(authorization)
    if job_id not in jobs or filename!=Path(filename).name or not (filename.endswith('.mp4') or filename.endswith('.srt')):
        raise HTTPException(404,"File not found")
    path=ROOT/job_id/filename
    if not path.is_file(): raise HTTPException(404,"File not found")
    return FileResponse(path,filename=filename)
