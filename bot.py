import asyncio
import os
import random
import threading
import sqlite3
import queue
import time
from datetime import datetime

from flask import Flask, render_template
from flask_socketio import SocketIO, emit

from mcpycore import MinecraftClient
from mcpycore.client.reconnect import ExponentialBackoff

# ---------- Configuration ----------
SERVER_HOST = os.getenv("MC_HOST", "nd-de2.hn21.xyz")
SERVER_PORT = int(os.getenv("MC_PORT", 20029))
BOT_USERNAME = os.getenv("MC_USERNAME", "WanderBotRedhat")
WEB_PORT = int(os.getenv("PORT", 8080))  # Koyeb sets PORT automatically

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
    c.execute(
        "SELECT timestamp, sender, message FROM messages ORDER BY id DESC LIMIT ?",
        (limit,)
    )
    rows = c.fetchall()
    conn.close()
    return [{"timestamp": r[0], "sender": r[1], "message": r[2]} for r in reversed(rows)]

# ---------- Flask + SocketIO Setup ----------
app = Flask(__name__)
app.config["SECRET_KEY"] = "minecraft-bot-secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

@app.route("/")
def index():
    return render_template("index.html")

# Thread-safe queue for messages from the web UI to the bot
web_to_bot_queue = queue.Queue()

@socketio.on("connect")
def handle_connect():
    print("[WEB] Client connected")
    # Send recent chat history when a client connects
    history = get_recent_messages(50)
    emit("chat_history", history)

@socketio.on("send_message")
def handle_send_message(data):
    """Receives a message from the web UI and queues it for the bot."""
    text = data.get("text", "").strip()
    if not text:
        return

    # Determine if it's a command (starts with /) or a chat message
    is_command = text.startswith("/")
    msg_type = "command" if is_command else "chat"

    # Queue for the bot to process
    web_to_bot_queue.put({"type": msg_type, "text": text})

    # Log it locally in the web UI as "you"
    save_message("WebUI", text)
    socketio.emit("new_message", {
        "timestamp": datetime.utcnow().isoformat(),
        "sender": "WebUI",
        "message": text
    })

# ---------- Bot Logic (runs in its own asyncio thread) ----------
async def wander_loop(client):
    """Makes the bot move, look, and interact randomly."""
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
            await client.move(
                x=target_x, y=target_y, z=target_z,
                yaw=random_yaw, pitch=random_pitch
            )

            if random.random() < 0.5:
                print("👋 Swinging arm")
                await client.swing_arm()
            else:
                print("🖱️ Using held item")
                await client.use_item(hand=0)

            if random.random() < 0.3:
                await client.look(
                    yaw=random.uniform(0, 360),
                    pitch=random.uniform(-90, 90)
                )
                print("👀 Looking around")

            await asyncio.sleep(random.uniform(2, 8))

        except Exception as e:
            print(f"⚠️ Wander loop error: {e}")
            await asyncio.sleep(5)

async def bot_main():
    """The main bot coroutine. Runs forever."""
    client = MinecraftClient(
        host=SERVER_HOST,
        port=SERVER_PORT,
        username=BOT_USERNAME,
        reconnect_policy=ExponentialBackoff(
            base_delay=5.0,
            max_delay=120.0,
            max_attempts=0,
        ),
    )

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
        # Ignore our own messages
        if sender_uuid == client.uuid:
            return
        sender_name = str(sender_uuid)  # Replace with player name if available
        print(f"[CHAT] {sender_name}: {message}")

        # Save to database
        save_message(sender_name, message)

        # Push to web UI in real-time
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

    # Start the bot (this blocks forever)
    await client.start()

def run_bot_thread():
    """Runs the bot's asyncio loop in a separate thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(bot_main())

def process_web_queue():
    """Polls the web-to-bot queue and sends messages/commands to the bot."""
    # We need a reference to the bot client's event loop to schedule coroutines.
    # This is a simplification; in production, use a proper cross-thread scheduler.
    while True:
        try:
            item = web_to_bot_queue.get(timeout=1)
            # The bot's loop is running in another thread.
            # We'll use a simple approach: store a reference to the loop.
            if bot_loop is not None:
                asyncio.run_coroutine_threadsafe(
                    send_to_minecraft(item["text"]),
                    bot_loop
                )
        except queue.Empty:
            pass
        except Exception as e:
            print(f"[QUEUE] Error: {e}")

# Global reference to the bot's event loop (set by run_bot_thread)
bot_loop = None

async def send_to_minecraft(text):
    """Sends a message or command to the Minecraft server."""
    # This needs access to the client object. We'll store it globally.
    global bot_client
    if bot_client is None:
        print("[BOT] Not connected yet, cannot send message.")
        return
    try:
        await bot_client.send_chat(text)  # Works for both chat and /commands
        print(f"[SENT] {text}")
    except Exception as e:
        print(f"[BOT] Failed to send: {e}")

# Store the client globally so send_to_minecraft can access it
bot_client = None

async def bot_main_with_global():
    global bot_client
    client = MinecraftClient(
        host=SERVER_HOST,
        port=SERVER_PORT,
        username=BOT_USERNAME,
        reconnect_policy=ExponentialBackoff(
            base_delay=5.0,
            max_delay=120.0,
            max_attempts=0,
        ),
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

if __name__ == "__main__":
    init_db()
    # Start the bot in a background thread
    bot_thread = threading.Thread(target=run_bot_thread, daemon=True)
    bot_thread.start()
    # Start a thread that polls the web queue
    queue_thread = threading.Thread(target=process_web_queue, daemon=True)
    queue_thread.start()
    # Start the Flask-SocketIO web server (blocking)
    print(f"🌐 Web interface at http://0.0.0.0:{WEB_PORT}")
    socketio.run(app, host="0.0.0.0", port=WEB_PORT, allow_unsafe_werkzeug=True)
