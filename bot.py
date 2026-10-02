import asyncio
import os
import random
import threading
import sqlite3
import queue
from datetime import datetime

from flask import Flask
from flask_socketio import SocketIO, emit

from mcpycore import MinecraftClient
from mcpycore.client.reconnect import ExponentialBackoff

# ---------- Configuration ----------
SERVER_HOST = os.getenv("MC_HOST", "nd-de2.hn21.xyz")
SERVER_PORT = int(os.getenv("MC_PORT", 20029))
BOT_USERNAME = os.getenv("MC_USERNAME", "WanderBot")
WEB_PORT = int(os.getenv("PORT", 8080))  # Koyeb sets PORT automatically

# ---------- Embedded HTML Web Interface ----------
HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Minecraft Bot Control</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #1a1a2e; color: #eee; display: flex; flex-direction: column; height: 100vh; }
        header { background: #16213e; padding: 15px 20px; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #0f3460; }
        header h1 { font-size: 18px; }
        #status { font-size: 14px; padding: 4px 12px; border-radius: 12px; background: #e94560; }
        #status.connected { background: #2ecc71; }
        #chat { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 8px; }
        .msg { max-width: 80%; padding: 8px 12px; border-radius: 8px; font-size: 14px; line-height: 1.4; word-wrap: break-word; }
        .msg .sender { font-weight: bold; font-size: 12px; opacity: 0.8; display: block; margin-bottom: 2px; }
        .msg.other { background: #0f3460; align-self: flex-start; }
        .msg.mine { background: #2ecc71; color: #000; align-self: flex-end; }
        .msg.system { background: #533483; align-self: center; font-size: 12px; text-align: center; }
        footer { display: flex; padding: 15px; background: #16213e; border-top: 2px solid #0f3460; gap: 10px; }
        #input { flex: 1; padding: 12px; border: none; border-radius: 8px; background: #1a1a2e; color: #eee; font-size: 14px; outline: none; }
        #input::placeholder { color: #666; }
        #send { padding: 12px 24px; background: #e94560; color: #fff; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; font-size: 14px; }
        #send:hover { background: #c73650; }
        .hint { font-size: 11px; opacity: 0.5; padding: 0 15px 10px; text-align: center; }
    </style>
</head>
<body>
    <header>
        <h1>🎮 Minecraft Bot Control</h1>
        <span id="status">Connecting...</span>
    </header>
    <div id="chat"></div>
    <div class="hint">Type a message or use /command for Minecraft commands</div>
    <footer>
        <input id="input" type="text" placeholder="Type a message or /command..." autocomplete="off" autofocus>
        <button id="send">Send</button>
    </footer>
    <script>
        const socket = io();
        const chatEl = document.getElementById("chat");
        const inputEl = document.getElementById("input");
        const sendBtn = document.getElementById("send");
        const statusEl = document.getElementById("status");

        function addMessage(sender, message, cls) {
            const div = document.createElement("div");
            div.className = "msg " + cls;
            if (sender) {
                const s = document.createElement("span");
                s.className = "sender";
                s.textContent = sender;
                div.appendChild(s);
            }
            div.appendChild(document.createTextNode(message));
            chatEl.appendChild(div);
            chatEl.scrollTop = chatEl.scrollHeight;
        }

        socket.on("connect", () => { statusEl.textContent = "Connected to WebUI"; statusEl.className = "connected"; });
        socket.on("disconnect", () => { statusEl.textContent = "Disconnected"; statusEl.className = ""; });
        socket.on("bot_status", (data) => {
            statusEl.textContent = "Bot: " + data.status;
            statusEl.className = data.status === "connected" ? "connected" : "";
        });
        socket.on("chat_history", (messages) => {
            chatEl.innerHTML = "";
            messages.forEach(m => addMessage(m.sender, m.message, m.sender === "WebUI" ? "mine" : "other"));
        });
        socket.on("new_message", (data) => addMessage(data.sender, data.message, data.sender === "WebUI" ? "mine" : "other"));

        function sendMessage() {
            const text = inputEl.value.trim();
            if (!text) return;
            socket.emit("send_message", { text: text });
            inputEl.value = "";
        }
        sendBtn.addEventListener("click", sendMessage);
        inputEl.addEventListener("keydown", (e) => { if (e.key === "Enter") sendMessage(); });
    </script>
</body>
</html>
"""

# ---------- Database Setup (SQLite) ----------
DB_PATH = "chat_history.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            sender TEXT NOT NULL,
            message TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def save_message(sender, message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages (timestamp, sender, message) VALUES (?, ?, ?)",
        (datetime.utcnow().isoformat(), sender, message)
    )
    conn.commit()
    conn.close()

def get_recent_messages(limit=50):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT timestamp, sender, message FROM messages ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [{"timestamp": r[0], "sender": r[1], "message": r[2]} for r in reversed(rows)]

# ---------- Flask + SocketIO Setup ----------
app = Flask(__name__)
app.config["SECRET_KEY"] = "minecraft-bot-secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

@app.route("/")
def index():
    return HTML_PAGE

# Thread-safe queue for messages from the web UI to the bot
web_to_bot_queue = queue.Queue()

@socketio.on("connect")
def handle_connect():
    print("[WEB] Client connected")
    history = get_recent_messages(50)
    emit("chat_history", history)

@socketio.on("send_message")
def handle_send_message(data):
    text = data.get("text", "").strip()
    if not text:
        return
    web_to_bot_queue.put({"text": text})
    save_message("WebUI", text)
    socketio.emit("new_message", {
        "timestamp": datetime.utcnow().isoformat(),
        "sender": "WebUI",
        "message": text
    })

# ---------- Bot Logic (runs in its own asyncio thread) ----------
bot_client = None
bot_loop = None

async def wander_loop(client):
    await asyncio.sleep(5)
    while True:
        try:
            dx = random.uniform(-5.0, 5.0)
            dz = random.uniform(-5.0, 5.0)
            current_pos = client.position
            target_x = current_pos.x + dx
            target_z = current_pos.z + dz
            target_y = current_pos.y

            random_yaw = random.uniform(0, 360)
            random_pitch = random.uniform(-45, 45)
            await client.look(yaw=random_yaw, pitch=random_pitch)
            await asyncio.sleep(0.5)

            print(f"🚶 Moving to ({target_x:.1f}, {target_y:.1f}, {target_z:.1f})")
            await client.move(x=target_x, y=target_y, z=target_z, yaw=random_yaw, pitch=random_pitch)

            if random.random() < 0.5:
                await client.swing_arm()
            else:
                await client.use_item(hand=0)

            if random.random() < 0.3:
                await client.look(yaw=random.uniform(0, 360), pitch=random.uniform(-90, 90))

            await asyncio.sleep(random.uniform(2, 8))
        except Exception as e:
            print(f"⚠️ Wander loop error: {e}")
            await asyncio.sleep(5)

async def send_to_minecraft(text):
    global bot_client
    if bot_client is None:
        print("[BOT] Not connected yet, cannot send message.")
        return
    try:
        await bot_client.send_chat(text)
        print(f"[SENT] {text}")
    except Exception as e:
        print(f"[BOT] Failed to send: {e}")

async def bot_main_with_global():
    global bot_client
    client = MinecraftClient(
        host=SERVER_HOST,
        port=SERVER_PORT,
        username=BOT_USERNAME,
        reconnect_policy=ExponentialBackoff(base_delay=5.0, max_delay=120.0, max_attempts=0),
    )
    bot_client = client

    @client.event
    async def on_connect(c):
        print(f"✅ Connected to {SERVER_HOST}:{SERVER_PORT}")
        socketio.emit("bot_status", {"status": "connected"})

    @client.event
    async def on_spawn(x, y, z):
        print(f"📍 Spawned at {x}, {y}, {z}")
        asyncio.create_task(wander_loop(client))

    @client.event
    async def on_chat(message, sender_uuid):
        if sender_uuid == client.uuid:
            return
        sender_name = str(sender_uuid)
        print(f"[CHAT] {sender_name}: {message}")
        save_message(sender_name, message)
        socketio.emit("new_message", {
            "timestamp": datetime.utcnow().isoformat(),
            "sender": sender_name,
            "message": message
        })

    @client.event
    async def on_disconnect(reason):
        print(f"❌ Disconnected: {reason}")
        socketio.emit("bot_status", {"status": "disconnected"})

    @client.event
    async def on_error(exc):
        print(f"⚠️ Error: {exc}")
        socketio.emit("bot_status", {"status": f"error: {exc}"})

    await client.start()

def run_bot_thread():
    global bot_loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot_loop = loop
    loop.run_until_complete(bot_main_with_global())

def process_web_queue():
    while True:
        try:
            item = web_to_bot_queue.get(timeout=1)
            if bot_loop is not None:
                asyncio.run_coroutine_threadsafe(send_to_minecraft(item["text"]), bot_loop)
        except queue.Empty:
            pass
        except Exception as e:
            print(f"[QUEUE] Error: {e}")

if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_bot_thread, daemon=True).start()
    threading.Thread(target=process_web_queue, daemon=True).start()
    print(f"🌐 Web interface at http://0.0.0.0:{WEB_PORT}")
    socketio.run(app, host="0.0.0.0", port=WEB_PORT, allow_unsafe_werkzeug=True)
