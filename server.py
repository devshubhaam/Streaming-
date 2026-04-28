import os
import asyncio
import threading
from flask import Flask, request, Response, send_from_directory
from telethon import TelegramClient
from telethon.sessions import StringSession

app = Flask(__name__, static_folder='public')

API_ID       = int(os.environ['API_ID'])
API_HASH     = os.environ['API_HASH']
SESSION      = os.environ['SESSION_STRING']
CHUNK_SIZE   = 1024 * 1024  # 1MB per chunk

# ── One persistent event loop in background thread ──
_loop = asyncio.new_event_loop()

def _start_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

threading.Thread(target=_start_loop, args=(_loop,), daemon=True).start()

def run_async(coro):
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result()

# ── Persistent Telegram client ──
_client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

async def _connect():
    if not _client.is_connected():
        await _client.connect()

run_async(_connect())

# ── Routes ──

@app.route('/')
def index():
    return send_from_directory('public', 'index.html')

@app.route('/api/video/<path:file_id>')
def stream_video(file_id):
    range_header = request.headers.get('Range', '')
    start = 0

    if range_header:
        try:
            start = int(range_header.replace('bytes=', '').split('-')[0])
        except Exception:
            start = 0

    def generate():
        offset = start
        while True:
            chunk = run_async(_fetch_chunk(file_id, offset, CHUNK_SIZE))
            if not chunk:
                break
            yield chunk
            if len(chunk) < CHUNK_SIZE:
                break  # last chunk
            offset += len(chunk)

    headers = {
        'Accept-Ranges': 'bytes',
        'Content-Type':  'video/mp4',
        'Cache-Control': 'no-cache',
    }

    if range_header:
        end_byte = start + CHUNK_SIZE - 1
        headers['Content-Range'] = f'bytes {start}-{end_byte}/*'
        return Response(generate(), status=206, headers=headers)

    return Response(generate(), status=200, headers=headers)

async def _fetch_chunk(file_id: str, offset: int, limit: int) -> bytes:
    data = b''
    async for chunk in _client.iter_download(
        file_id,
        offset=offset,
        request_size=limit,
        limit=limit,
    ):
        data += chunk
        break  # one chunk only
    return data

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    print(f'🚀 TGStream (Python) running on port {port}')
    app.run(host='0.0.0.0', port=port, threaded=True)
