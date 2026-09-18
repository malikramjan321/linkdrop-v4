# LinkDrop V5

Multi-source public-media downloader architecture.

- `frontend/`: static responsive frontend (Netlify)
- `backend/`: FastAPI + direct-file probe + yt-dlp + FFmpeg (Render/Docker)
- Direct public media is detected before extractor fallback.
- Extractor failures return structured codes such as `SOURCE_AUTH_REQUIRED`, `UNSUPPORTED_SOURCE`, and `DRM_OR_PROTECTED`.
- No cookies, login automation, DRM bypass, or private-content bypass is included.

## Upgrade existing Render service
Replace the repository contents with V5 and push to `main`. Render should auto-deploy because the backend root remains `backend`.

## Frontend
Set `frontend/config.js` to your backend URL, e.g. `window.LINKDROP_API="https://linkdrop-v4.onrender.com";`, then deploy `frontend/` to Netlify.
