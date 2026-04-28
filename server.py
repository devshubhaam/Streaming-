import os
import math
import asyncio
import threading
from flask import Flask, request, Response, send_from_directory
from pyrogram import Client

app = Flask(__name__, static_folder='public')

API_ID   = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION  = os.environ['SESSION_STRING']  # Pyrogram session string

CHUNK_SIZE = 1024 * 1024  # 1MB

# ── Background event loop ──
_loop = asyncio.new_event_loop()
threading.Thread(target=_loop.run_forever, daemon=True).start()

def run_async(coro):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result()

# ── Pyrogram client ──
_client = Client(
    name="tgstream",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION,
    in_memory=True,
    no_updates=True,
)

run_async(_client.start())
print("✅ Pyrogram connected")

async def _stream_chunk(file_id: str, offset: int, parts: int) -> bytes:
    data = b''
    async for chunk in _client.stream_media(file_id, offset=offset, limit=parts):
        data += chunk
    return data

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

    limit = (end - start + 1) if end else CHUNK_SIZE

    # Pyrogram needs 1MB-aligned offsets
    part_size   = 1024 * 1024
    first_part  = math.floor(start / part_size)
    last_part   = math.ceil((start + limit) / part_size)
    tg_offset   = first_part * part_size
    skip_bytes  = start - tg_offset
    parts_count = last_part - first_part

    def generate():
        try:
            data = run_async(_stream_chunk(file_id, tg_offset, parts_count))
            yield data[skip_bytes: skip_bytes + limit]
        except Exception as e:
            print(f"Stream error: {e}")
            yield b''

    headers = {
        'Accept-Ranges':  'bytes',
        'Content-Type':   'video/mp4',
        'Cache-Control':  'no-cache',
        'Content-Length': str(limit),
    }

    if range_header:
        end_byte = start + limit - 1
        headers['Content-Range'] = f'bytes {start}-{end_byte}/*'
        return Response(generate(), status=206, headers=headers)

    return Response(generate(), status=200, headers=headers)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    print(f'🚀 TGStream (Pyrogram) on port {port}')
    app.run(host='0.0.0.0', port=port, threaded=True)
