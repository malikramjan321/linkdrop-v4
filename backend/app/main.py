import os, re, shutil, threading, time, uuid, urllib.request
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from yt_dlp import YoutubeDL

APP_ORIGINS=[x.strip() for x in os.getenv('APP_ORIGINS','*').split(',') if x.strip()]
STORE=Path(os.getenv('DOWNLOAD_DIR','/tmp/linkdrop')); STORE.mkdir(parents=True,exist_ok=True)
TTL=int(os.getenv('FILE_TTL_SECONDS','1800'))
MAX_HEIGHT=int(os.getenv('MAX_VIDEO_HEIGHT','1080'))
app=FastAPI(title='LinkDrop V5 API',version='5.0.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
JOBS={}; LOCK=threading.Lock()

class AnalyzeIn(BaseModel): url: HttpUrl
class JobIn(BaseModel): url: HttpUrl; format_id: str|None=None; mode: str='video'

def safe_public_url(raw:str):
    u=urlparse(raw)
    if u.scheme not in ('http','https'): raise HTTPException(400,'Only HTTP/HTTPS URLs are supported.')
    h=(u.hostname or '').lower()
    if h in {'localhost','127.0.0.1','::1'} or h.endswith('.local') or re.match(r'^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)',h):
        raise HTTPException(400,'Private-network URLs are not supported.')
    return raw

def direct_probe(raw:str):
    """Detect openly downloadable direct media without an extractor."""
    req=urllib.request.Request(raw,method='HEAD',headers={'User-Agent':'LinkDrop/5.0'})
    try:
        with urllib.request.urlopen(req,timeout=12) as r:
            ct=(r.headers.get('Content-Type') or '').split(';')[0].lower()
            size=r.headers.get('Content-Length')
            final=r.geturl()
            cd=r.headers.get('Content-Disposition') or ''
    except Exception:
        return None
    media=ct.startswith(('video/','audio/','image/')) or ct in {'application/pdf','application/zip','application/octet-stream'}
    if not media:return None
    name=''
    m=re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';]+)',cd,re.I)
    if m:name=m.group(1)
    if not name:name=Path(urlparse(final).path).name or 'download'
    return {'kind':'direct','title':name,'uploader':urlparse(final).hostname,'thumbnail':None,'duration':None,'webpage_url':raw,'extractor':'DirectFile','direct_url':final,'content_type':ct,'size':int(size) if size and size.isdigit() else None,'formats':[{'id':'direct','ext':Path(name).suffix.lstrip('.') or ct.split('/')[-1],'height':None,'fps':None,'vcodec':'direct' if ct.startswith('video/') else 'none','acodec':'direct' if ct.startswith('audio/') else 'none','filesize':int(size) if size and size.isdigit() else None,'note':'Direct file'}]}

def classify_error(msg:str):
    low=msg.lower()
    if 'not a bot' in low or 'sign in' in low or 'cookies' in low:return 'SOURCE_AUTH_REQUIRED'
    if 'drm' in low:return 'DRM_OR_PROTECTED'
    if 'unsupported url' in low:return 'UNSUPPORTED_SOURCE'
    if 'private video' in low or 'private' in low:return 'PRIVATE_SOURCE'
    if 'geo' in low or 'country' in low:return 'GEO_RESTRICTED'
    return 'EXTRACTOR_FAILED'

def analyze(raw:str):
    safe_public_url(raw)
    direct=direct_probe(raw)
    if direct:return direct
    opts={'quiet':True,'no_warnings':True,'skip_download':True,'noplaylist':True,'extract_flat':False}
    with YoutubeDL(opts) as ydl:
        info=ydl.extract_info(raw,download=False)
        info=ydl.sanitize_info(info)
    formats=[]
    seen=set()
    for f in info.get('formats') or []:
        fid=str(f.get('format_id') or '')
        if not fid or fid in seen: continue
        seen.add(fid)
        h=f.get('height'); v=f.get('vcodec'); a=f.get('acodec'); ext=f.get('ext')
        if h and h>MAX_HEIGHT: continue
        if v=='none' and a=='none': continue
        formats.append({'id':fid,'ext':ext,'height':h,'fps':f.get('fps'),'vcodec':v,'acodec':a,'filesize':f.get('filesize') or f.get('filesize_approx'),'note':f.get('format_note')})
    formats.sort(key=lambda x:((x['height'] or 0),x['filesize'] or 0),reverse=True)
    return {'kind':'extracted','title':info.get('title'),'uploader':info.get('uploader') or info.get('channel'),'thumbnail':info.get('thumbnail'),'duration':info.get('duration'),'webpage_url':info.get('webpage_url') or raw,'extractor':info.get('extractor_key') or info.get('extractor'),'formats':formats[:40]}

def progress_hook(job_id):
    def hook(d):
        with LOCK:
            j=JOBS.get(job_id)
            if not j:return
            if d.get('status')=='downloading':
                total=d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                got=d.get('downloaded_bytes') or 0
                j['status']='downloading'; j['progress']=round(got*100/total,1) if total else None
            elif d.get('status')=='finished': j['status']='processing'; j['progress']=100
    return hook

def run_job(job_id,raw,format_id,mode):
    folder=STORE/job_id; folder.mkdir(parents=True,exist_ok=True)
    try:
        if mode=='audio': fmt='bestaudio/best'
        elif format_id: fmt=f'{format_id}+bestaudio/{format_id}/best[height<={MAX_HEIGHT}]'
        else: fmt=f'bestvideo[height<={MAX_HEIGHT}]+bestaudio/best[height<={MAX_HEIGHT}]'
        opts={'format':fmt,'outtmpl':str(folder/'%(title).120s-%(id)s.%(ext)s'),'noplaylist':True,'restrictfilenames':True,'progress_hooks':[progress_hook(job_id)],'merge_output_format':'mp4','quiet':True,'no_warnings':True}
        if mode=='audio': opts['postprocessors']=[{'key':'FFmpegExtractAudio','preferredcodec':'mp3','preferredquality':'192'}]
        with YoutubeDL(opts) as ydl: ydl.download([raw])
        files=[p for p in folder.iterdir() if p.is_file() and not p.name.endswith(('.part','.ytdl'))]
        if not files: raise RuntimeError('No output file was created.')
        p=max(files,key=lambda x:x.stat().st_mtime)
        with LOCK: JOBS[job_id].update(status='ready',progress=100,file=str(p),filename=p.name,size=p.stat().st_size,ready_at=time.time())
    except Exception as e:
        with LOCK: JOBS[job_id].update(status='error',error=str(e)[:500])

def cleanup_loop():
    while True:
        time.sleep(60); now=time.time()
        with LOCK:
            old=[k for k,v in JOBS.items() if v.get('ready_at') and now-v['ready_at']>TTL]
        for k in old:
            shutil.rmtree(STORE/k,ignore_errors=True)
            with LOCK:JOBS.pop(k,None)
threading.Thread(target=cleanup_loop,daemon=True).start()

@app.get('/health')
def health(): return {'ok':True,'version':'5.0.0','engine':'multi-source','direct_files':True,'extractor':'yt-dlp'}
@app.post('/api/analyze')
def api_analyze(body:AnalyzeIn):
    try:return analyze(str(body.url))
    except HTTPException:raise
    except Exception as e:
        msg=str(e)[:500]
        raise HTTPException(424,{'code':classify_error(msg),'message':msg})
@app.post('/api/jobs')
def create_job(body:JobIn):
    raw=safe_public_url(str(body.url)); jid=uuid.uuid4().hex
    with LOCK:JOBS[jid]={'id':jid,'status':'queued','progress':0,'created_at':time.time()}
    threading.Thread(target=run_job,args=(jid,raw,body.format_id,body.mode),daemon=True).start()
    return {'id':jid,'status':'queued'}
@app.get('/api/jobs/{job_id}')
def get_job(job_id:str):
    with LOCK:j=JOBS.get(job_id)
    if not j:raise HTTPException(404,'Job not found.')
    out={k:v for k,v in j.items() if k!='file'}
    if j.get('status')=='ready':out['download_url']=f'/api/files/{job_id}'
    return out
@app.get('/api/files/{job_id}')
def get_file(job_id:str):
    with LOCK:j=JOBS.get(job_id)
    if not j or j.get('status')!='ready':raise HTTPException(404,'File not ready.')
    p=Path(j['file'])
    if not p.exists():raise HTTPException(410,'File expired.')
    return FileResponse(p,filename=j['filename'],media_type='application/octet-stream')
