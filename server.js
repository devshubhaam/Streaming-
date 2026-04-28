require('dotenv').config();
const express = require('express');
const https = require('https');
const http = require('http');
const path = require('path');

const app = express();
const BOT_TOKEN = process.env.BOT_TOKEN;
const PORT = process.env.PORT || 3000;

if (!BOT_TOKEN) {
  console.error('❌ BOT_TOKEN missing in .env');
  process.exit(1);
}

// Serve static files
app.use(express.static(path.join(__dirname, 'public')));

// Cache file_path to avoid repeated API calls
const filePathCache = {};

async function getFilePath(file_id) {
  if (filePathCache[file_id]) return filePathCache[file_id];

  return new Promise((resolve, reject) => {
    const url = `https://api.telegram.org/bot${BOT_TOKEN}/getFile?file_id=${file_id}`;
    https.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          const json = JSON.parse(data);
          if (!json.ok) return reject(new Error(json.description || 'Telegram API error'));
          const file_path = json.result.file_path;
          filePathCache[file_id] = file_path;
          resolve(file_path);
        } catch (e) {
          reject(e);
        }
      });
    }).on('error', reject);
  });
}

// Stream video with range support
app.get('/api/video/:file_id', async (req, res) => {
  const { file_id } = req.params;

  try {
    const file_path = await getFilePath(file_id);
    const videoUrl = `https://api.telegram.org/file/bot${BOT_TOKEN}/${file_path}`;

    // First, get content-length via HEAD
    const headData = await new Promise((resolve, reject) => {
      https.request(videoUrl, { method: 'HEAD' }, (r) => {
        resolve({ contentLength: parseInt(r.headers['content-length'] || '0'), contentType: r.headers['content-type'] || 'video/mp4' });
      }).on('error', reject).end();
    });

    const { contentLength, contentType } = headData;
    const rangeHeader = req.headers.range;

    if (rangeHeader && contentLength) {
      // Parse range
      const parts = rangeHeader.replace(/bytes=/, '').split('-');
      const start = parseInt(parts[0], 10);
      const end = parts[1] ? parseInt(parts[1], 10) : Math.min(start + 1024 * 1024, contentLength - 1);
      const chunkSize = end - start + 1;

      res.writeHead(206, {
        'Content-Range': `bytes ${start}-${end}/${contentLength}`,
        'Accept-Ranges': 'bytes',
        'Content-Length': chunkSize,
        'Content-Type': contentType,
        'Cache-Control': 'no-store',
      });

      https.get(videoUrl, { headers: { Range: `bytes=${start}-${end}` } }, (stream) => {
        stream.pipe(res);
        stream.on('error', () => res.end());
      }).on('error', () => res.end());

    } else {
      // Full response
      res.writeHead(200, {
        'Content-Length': contentLength,
        'Content-Type': contentType,
        'Accept-Ranges': 'bytes',
        'Cache-Control': 'no-store',
      });

      https.get(videoUrl, (stream) => {
        stream.pipe(res);
        stream.on('error', () => res.end());
      }).on('error', () => res.end());
    }

  } catch (err) {
    console.error('Video error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// All other routes -> index.html (SPA)
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.listen(PORT, () => {
  console.log(`🚀 TGStream running at http://localhost:${PORT}`);
});
