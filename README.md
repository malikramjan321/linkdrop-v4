# LinkDrop V4

V4 separates the responsive frontend from the media-processing backend.

## 1. Backend
Deploy `backend/` on a Docker-compatible host. It needs Python and FFmpeg.

Environment variables:
- `APP_ORIGINS=https://YOUR-NETLIFY-SITE.netlify.app`
- `FILE_TTL_SECONDS=1800`
- `MAX_VIDEO_HEIGHT=1080`

Test: `GET /health`

## 2. Frontend
Open `frontend/config.js` and replace `http://localhost:8080` with the deployed backend HTTPS URL. Then deploy the `frontend/` folder to Netlify.

## Local test
Backend:
`docker build -t linkdrop-api backend && docker run --rm -p 8080:8080 -e APP_ORIGINS=http://localhost:5500 linkdrop-api`

Serve frontend with any static server on port 5500.

## Scope
This build intentionally has no cookie import, account-login automation, private-content access, DRM bypass, or proxy evasion. Use it only for media you own or have permission to download. Some platforms can change their delivery systems and may stop working until yt-dlp is updated.
