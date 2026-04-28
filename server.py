import os
import asyncio
import threading
import requests
from flask import Flask, request, Response, send_from_directory
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest

app = Flask(__name__, static_folder='public')

API_ID       = int(os.environ['API_ID'])
API_HASH     = os.environ['API_HASH']
SESSION      = os.environ['SESSION_STRING']
BOT_TOKEN    = os.environ.get('BOT_TOKEN', '')  # optional, for getFile fallback
CHUNK_SIZE   = 512 * 1024  # 512KB

# ── One persistent event loop in background thread ──
_loop = asyncio.new_event_loop()

def _start_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

threading.Thread(target=_start_loop, args=(_loop,), daemon=True).start()

def run_async(coro):
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result()

# ── Persistent Telegram client (MTProto) ──
_client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

async def _connect():
    await _client.connect()
    print('✅ Telegram MTProto connected')

run_async(_connect())

# ── file_id -> media object cache ──
_media_cache = {}

async def _resolve_media(file_id: str):
    """Get Telethon media object from a Bot API file_id string."""
    if file_id in _media_cache:
        return _media_cache[file_id]

    # Use Bot API getFile to get the file_path
    if not BOT_TOKEN:
        raise Exception('BOT_TOKEN not set — needed to resolve file_id')

    r = requests.get(
        f'https://api.telegram.org/bot{BOT_TOKEN}/getFile',
        params={'file_id': file_id},
        timeout=10
    )
    data = r.json()
    if not data.get('ok'):
        raise Exception(f"Telegram getFile error: {data.get('description')}")

    file_path = data['result']['file_path']
    file_url  = f'https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}'

    # Store URL for direct streaming
    _media_cache[file_id] = {'url': file_url, 'type': 'url'}
    return _media_cache[file_id]

async def _get_message_media(file_id: str):
    """
    Alternative: search recent messages for this file_id to get Telethon media.
    Uses 'me' (saved messages) as the search space.
    """
    if file_id in _media_cache:
        return _media_cache[file_id]

    async for msg in _client.iter_messages('me', limit=200):
        if msg.media and hasattr(msg.media, 'document'):
            doc = msg.media.document
            if doc.id and str(doc.id) in file_id:
                _media_cache[file_id] = msg.media
                return msg.media
    return None

# ── Routes ──

@app.route('/')
def index():
    return send_from_directory('public', 'index.html')

@app.route('/api/video/<path:file_id>')
def stream_video(file_id):
    range_header = request.headers.get('Range', '')
    start = 0
    end   = None

    if range_header:
        try:
            parts = range_header.replace('bytes=', '').split('-')
            start = int(parts[0]) if parts[0] else 0
            end   = int(parts[1]) if len(parts) > 1 and parts[1] else None
        except Exception:
            start = 0

    try:
        media_info = run_async(_resolve_media(file_id))
    except Exception as e:
        return {'error': str(e)}, 500

    # Stream directly from Telegram CDN URL with range
    tg_url = media_info['url']
    req_headers = {}
    if range_header:
        req_headers['Range'] = range_header

    tg_resp = requests.get(tg_url, headers=req_headers, stream=True, timeout=30)

    def generate():
        for chunk in tg_resp.iter_content(chunk_size=CHUNK_SIZE):
            if chunk:
                yield chunk

    resp_headers = {
        'Accept-Ranges': 'bytes',
        'Content-Type': tg_resp.headers.get('Content-Type', 'video/mp4'),
        'Cache-Control': 'no-cache',
    }

    if 'Content-Range' in tg_resp.headers:
        resp_headers['Content-Range'] = tg_resp.headers['Content-Range']
    if 'Content-Length' in tg_resp.headers:
        resp_headers['Content-Length'] = tg_resp.headers['Content-Length']

    status = tg_resp.status_code  # 206 if range, 200 otherwise

    return Response(generate(), status=status, headers=resp_headers)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    print(f'🚀 TGStream running on port {port}')
    app.run(host='0.0.0.0', port=port, threaded=True)
