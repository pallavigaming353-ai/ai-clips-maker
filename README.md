# AI Clips Maker

Web-only video clip maker: Next.js frontend and FastAPI video-processing backend.

## Current milestone

Implemented in source (not yet integration-tested or deployed):
- Paste-link-first UI with best-effort public YouTube watch-link import and direct MP4/MOV import from explicitly configured trusted HTTPS hosts (not YouTube watch pages).\n- MP4/MOV upload fallback to local FastAPI server (2 GiB default limit).
- Hindi transcription via faster-whisper (CPU).
- User-selectable deterministic speech-density clip windows of 30 seconds, 60 seconds, and 30 minutes when input is long enough (30 and 60 seconds selected by default).
- FFmpeg 9:16 center crop and 16:9 letterbox exports.
- Burned-in Hindi captions (requires FFmpeg libass) plus separate SRT files; job polling, HTML video preview, and MP4/SRT downloads.

**Not implemented:** reliable import for every YouTube video, semantic AI ranking, authentication, cloud object storage, durable queues, job cleanup, production deployment. Processing is memory-local and is lost on restart. Do not expose the backend publicly without auth, quotas, secure storage, and retention controls.

## Link import configuration

Set `DIRECT_VIDEO_HOSTS=your-trusted-cdn.example` in the backend environment to permit direct HTTPS MP4/MOV URLs from that exact host. No hosts are enabled by default. Do not add arbitrary user-provided hosts or private/internal services. The current URL importer is an initial implementation and has not undergone SSRF penetration testing; DNS rebinding and network-level egress controls require additional hardening before public exposure. Public YouTube watch links use a separate yt-dlp-based importer. It may fail due to platform changes, access restrictions, or unavailable MP4 formats; it does not bypass logins or DRM. Use only sources you own or have permission to process.

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

The 30-minute windows are rendered only when the source is at least 30 minutes long. Video crops are center-based, not speaker-tracked. Subtitle output is both burned into MP4 and provided as separate SRT when FFmpeg supports the subtitles/libass filter. The speech-density algorithm is a baseline, not a guarantee of engaging highlights. A production release requires persistent workers, authenticated access, storage quotas, and automatic deletion.

## Verification
GitHub Actions includes Python core tests, an FFmpeg synthetic-video rendering smoke test, and a Next.js build check. CI outcomes have not yet been confirmed. YouTube import has not been tested against a live video. Caption font rendering depends on Hindi-capable fonts installed on the processing host. Optional CLIPPER_API_TOKEN protects API endpoints but the current browser UI does not support token-authenticated preview/download; use only a local trusted development environment until end-to-end user authentication is implemented.

## Backend container (local testing only)

```bash
docker build -t ai-clips-maker-api ./backend
docker run --rm -p 127.0.0.1:8000:8000 -e MAX_ACTIVE_JOBS=1 ai-clips-maker-api
```

The container includes FFmpeg and Noto fonts for Devanagari captions. This is a **local test configuration**, not a public deployment recipe. Production still needs authenticated sessions, protected file delivery, a durable queue, cleanup policies, resource isolation, and storage persistence. MAX_ACTIVE_JOBS currently limits accepted active jobs in a single process and does not provide distributed admission control. Do not run multiple workers as a workaround.

## Run the website and processor together (local development)

Install Docker Engine with the Compose plugin, then from the repository root:

```bash
docker compose up --build
```

Open `http://localhost:3000` in a browser on the same computer. The FastAPI health endpoint is `http://localhost:8000/api/health`. The backend stores imported media and generated clips in the persistent `clipper_data` Docker volume.

**Important:** This setup binds both services to the local loopback interface only. It is not a public deployment and is not directly accessible from an iPhone on another device. Do not expose this development stack to the internet without adding proper user authentication, job ownership, download authorization, resource quotas, and secure ingress. The optional backend bearer token is not wired into the frontend.

YouTube imports are best-effort and may be blocked by platform restrictions. Download and process only content you are authorized to use. Long videos require substantial disk space, CPU time, and memory.

## Render deployment preparation (not deployed)

Selected Render workspace: **Test's workspace**. No services have been created.

The application requires **two separate web services**:

1. **API processor**: Docker runtime, repository `pallavigaming353-ai/ai-clips-maker`, branch `main`, Dockerfile `backend/Dockerfile`, build context `backend`. Requires FFmpeg, CPU/memory for faster-whisper, and persistent writable disk at `/srv/clipper-data`.
2. **Next.js frontend**: Docker runtime, same repository and branch, Dockerfile `Dockerfile.frontend`, build context `.`. Set build argument `NEXT_PUBLIC_API_BASE_URL` to the final public HTTPS backend URL **before building**.

For the API, set `CLIPPER_DATA_DIR=/srv/clipper-data`, `CORS_ORIGINS=https://<frontend-host>`, `MAX_ACTIVE_JOBS=1`, and `WHISPER_MODEL=small`. Never commit secrets. The existing browser frontend does **not** send `CLIPPER_API_TOKEN`, so enabling that token would currently block its API calls.

**Deployment blockers before any public launch:** implement real user authentication and job ownership, protect downloads, use a durable job store/queue and retention cleanup, and validate a real YouTube import plus FFmpeg render. Existing in-memory job state is lost on restart; mounted disk alone does not fix it. Render instance, disk, compute, and bandwidth costs must be reviewed and approved before creating services. The frontend's build-time API URL must match the deployed backend origin.

Local development: `docker compose up --build`. This is not a public production configuration.

### Output retention

Completed and failed jobs are eligible for deletion after `JOB_RETENTION_HOURS` (default: 24 hours). Cleanup currently runs **at API startup only**, not continuously. The age is measured from the persisted `job.json` file modification time. Download generated clips promptly; do not treat the output disk as permanent storage. Jobs without persisted metadata are not automatically cleaned by this routine.

### Production API safety gate

Set `DEPLOYMENT_ENV=production` and a strong, randomly generated `CLIPPER_API_TOKEN` for the API service. The backend intentionally refuses to start in production mode without the token. **This is not a complete deployment solution:** the current browser frontend does not provide a secure authenticated proxy and will fail to access a token-protected backend. Never put `CLIPPER_API_TOKEN` into `NEXT_PUBLIC_*` variables or browser JavaScript. Implement server-side authenticated forwarding and user access control before public launch. `DEPLOYMENT_ENV` defaults to `development` for local use only.

### Private website authentication (new)

The browser now calls same-origin `/api/*` endpoints. The Next.js server forwards allowed requests to `CLIPPER_BACKEND_URL` and injects `CLIPPER_API_TOKEN` on the server; never expose this token through `NEXT_PUBLIC_*`.

Configure `CLIPPER_SITE_USER`, a strong `CLIPPER_SITE_PASSWORD`, `CLIPPER_BACKEND_URL`, and `CLIPPER_API_TOKEN` as **server-side environment variables**. The website responds with HTTP Basic authentication challenges for `/` and `/api/*`; HTTPS is mandatory outside localhost because Basic credentials are sent on every request. Do not reuse account passwords. This is single-owner access, not multi-user account management, and does not provide per-user job ownership. Rate limiting, audit logging, and full deployment validation remain outstanding.

For local Compose, create a private `.env` file (do not commit it) containing:
```dotenv
CLIPPER_API_TOKEN=replace-with-long-random-token
CLIPPER_SITE_USER=owner
CLIPPER_SITE_PASSWORD=replace-with-long-random-password
```
Then run `docker compose up --build`. The browser connects to http://localhost:3000; the frontend reaches the API at http://api:8000 inside Compose. Production requires HTTPS and secure deployment secrets.
