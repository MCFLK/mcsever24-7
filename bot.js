const mineflayer = require('mineflayer');
const http = require('http');

const HOST = process.env.MINECRAFT_IP || 'nd-de2.hn21.xyz';
const MC_PORT = parseInt(process.env.MINECRAFT_PORT || '20029');
const BOT_NAME = process.env.BOT_NAME || 'AFK_King_Redhat';
const WEB_PORT = parseInt(process.env.PORT || '8080');
const PANEL_KEY = process.env.PANEL_KEY || '';

let bot = null;
let reconnectDelay = 10000;
let moveTimer = null;
const chatLog = [];

const addLog = (line) => {
  chatLog.push(line);
  if (chatLog.length > 20) chatLog.shift();
};

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// --- Anti-AFK random movement ---
function startMovement(b) {
  const dirs = ['forward', 'back', 'left', 'right'];
  const step = () => {
    if (bot !== b) return;
    try {
      const dir = dirs[Math.floor(Math.random() * dirs.length)];
      b.setControlState(dir, true);
      if (Math.random() < 0.35) b.setControlState('jump', true);

      setTimeout(() => {
        if (bot !== b) return;
        try {
          b.setControlState(dir, false);
          b.setControlState('jump', false);
          b.look(Math.random() * Math.PI * 2, Math.random() - 0.5, false);
        } catch (e) {}
        moveTimer = setTimeout(step, 2000 + Math.random() * 6000);
      }, 300 + Math.random() * 1200);
    } catch (e) {
      console.log('[MOVE] error:', e.message);
    }
  };
  step();
}

// --- Bot connection with auto-reconnect ---
function connect() {
  console.log(`[BOT] Connecting to ${HOST}:${MC_PORT}...`);
  const b = mineflayer.createBot({
    host: HOST,
    port: MC_PORT,
    username: BOT_NAME,
    version: '1.21.1',
    hideErrors: true,
  });
  bot = b;

  b.once('spawn', () => {
    console.log(`[SUCCESS] ${BOT_NAME} joined the server!`);
    reconnectDelay = 10000;
    startMovement(b);
  });

  b.on('message', (m) => addLog(m.toString()));
  b.on('kicked', (reason) => console.log('[KICKED]', JSON.stringify(reason)));
  b.on('error', (err) => console.log('[ERROR]', err.message));

  b.once('end', () => {
    console.log(`[BOT] Disconnected. Retrying in ${Math.round(reconnectDelay / 1000)}s...`);
    if (bot === b) bot = null;
    clearTimeout(moveTimer);
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 1.5, 120000);
  });
}

// --- Web control panel ---
http
  .createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const key = url.searchParams.get('key') || '';

    if (PANEL_KEY && key !== PANEL_KEY) {
      res.writeHead(403, { 'Content-Type': 'text/plain' });
      return res.end('Forbidden: missing or wrong key.');
    }
    const keyQs = PANEL_KEY ? `?key=${encodeURIComponent(key)}` : '';

    if (url.pathname === '/send') {
      const msg = (url.searchParams.get('msg') || '').trim();
      if (msg && bot) {
        try {
          bot.chat(msg);
          addLog(`>> ${msg}`);
          console.log('[WEB PANEL] Sent:', msg);
        } catch (e) {
          console.log('[WEB PANEL] Failed:', e.message);
        }
      }
      res.writeHead(303, { Location: '/' + keyQs });
      return res.end();
    }

    const online = !!(bot && bot.entity);
    const logHtml = chatLog.map(esc).join('<br>') || 'No messages yet.';
    const keyField = PANEL_KEY ? `<input type="hidden" name="key" value="${esc(key)}">` : '';

    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(`<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(BOT_NAME)} Control Panel</title>
<style>
body{font-family:'Segoe UI',Tahoma,sans-serif;background:#121212;color:#e0e0e0;text-align:center;padding:40px 20px}
.card{background:#1e1e1e;max-width:560px;margin:0 auto;padding:30px;border-radius:12px;border:1px solid #333}
h1{color:#4caf50;margin-bottom:5px}
.status{font-weight:bold;padding:5px 10px;border-radius:5px;background:#333;display:inline-block;margin-bottom:20px}
.online{color:#4caf50}.offline{color:#f44336}
input[type=text]{width:100%;padding:12px;border:1px solid #444;background:#2a2a2a;color:#fff;border-radius:6px;font-size:16px;box-sizing:border-box}
button{padding:12px 24px;background:#4caf50;color:#fff;border:none;border-radius:6px;font-size:16px;cursor:pointer;font-weight:bold}
.log{text-align:left;background:#111;border:1px solid #333;border-radius:6px;padding:10px;margin-top:20px;font-family:monospace;font-size:13px;max-height:250px;overflow-y:auto}
.hint{font-size:13px;color:#888;margin-top:10px}a{color:#4caf50}
</style></head><body><div class="card">
<h1>${esc(BOT_NAME)} Control Panel</h1>
<div class="status">Status: <span class="${online ? 'online' : 'offline'}">${online ? 'ONLINE' : 'CONNECTING/OFFLINE'}</span></div>
<form action="/send" method="get">${keyField}
<p><input type="text" name="msg" placeholder="Chat message or /command" required autocomplete="off" autofocus></p>
<p><button type="submit">Send</button></p></form>
<div class="hint">Start with <b>/</b> to run a command (bot must be OP), e.g. <code>/gamemode creative ${esc(BOT_NAME)}</code></div>
<div class="log">${logHtml}</div>
<p><a href="/${keyQs}">Refresh</a></p>
<div class="hint">Connected to: <strong>${esc(HOST)}:${MC_PORT}</strong></div>
</div></body></html>`);
  })
  .listen(WEB_PORT, '0.0.0.0', () => console.log(`[KOYEB] Panel active on port ${WEB_PORT}`));

connect();
