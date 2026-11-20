# AI Clips Maker

Web-only video clip maker: Next.js frontend and FastAPI video-processing backend.

## Current milestone

Implemented in source (not yet integration-tested or deployed):
- MP4/MOV upload to local FastAPI server (2 GiB default limit).
- Hindi transcription via faster-whisper (CPU).
- Deterministic speech-density clip windows of 30 seconds, 60 seconds, and 30 minutes when input is long enough.
- FFmpeg 9:16 center crop and 16:9 letterbox exports.
- Separate Hindi SRT files; job polling, HTML video preview, and MP4/SRT downloads.

**Not implemented:** authorized YouTube import, semantic AI ranking, burned-in subtitles, authentication, cloud object storage, durable queues, job cleanup, production deployment. Processing is memory-local and is lost on restart. Do not expose the backend publicly without auth, quotas, secure storage, and retention controls.

## Local development

Requirements: Node.js 20.9+, Python 3.11+, ffmpeg and ffprobe on PATH. CPU transcription/rendering of a two-hour source can take considerable time and disk space.

Backend terminal:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend terminal (repository root):

```bash
npm install
npm run dev
```

Open http://localhost:3000. The UI defaults to http://localhost:8000 for its API. For remote development, set NEXT_PUBLIC_API_BASE_URL to the HTTPS backend origin and configure CORS_ORIGINS accordingly. Do not deploy an unauthenticated backend on a public endpoint.

## Known limitations

The 30-minute windows are rendered only when the source is at least 30 minutes long. Video crops are center-based, not speaker-tracked. Subtitle output is separate SRT, not burned into MP4. The speech-density algorithm is a baseline, not a guarantee of engaging highlights. A production release requires persistent workers, authenticated access, storage quotas, and automatic deletion.
