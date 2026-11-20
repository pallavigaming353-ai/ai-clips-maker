# AI Clips Maker

Responsive web-only AI video clipper, built with Next.js.

## Status
Frontend scaffold committed. The upload picker is local-only and **does not upload or process videos yet**. Generate Clips is disabled until a real processing API is implemented. YouTube import, transcription, clip selection, preview, and MP4/SRT export are pending.

## Run locally
Requires Node.js 20.9+.

```bash
npm install
npm run dev
```

Visit http://localhost:3000.

## Roadmap
1. FastAPI job service, authenticated uploads and temporary object storage.
2. Hindi transcription using faster-whisper and SRT generation.
3. Content-aware 30-second, 60-second and 30-minute highlight selection.
4. FFmpeg video export in 9:16 and 16:9 with Hindi captions.
5. Preview, clip trimming, download, queue progress, retries and deployment.
6. Authorized YouTube import where permitted.

## Safety and reliability
Only process content that the uploader owns or has permission to use. Do not commit API keys or uploaded media. Production needs durable workers and storage; a serverless frontend alone is insufficient for two-hour renders.
