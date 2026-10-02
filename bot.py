import os
import time
import math
import random
import html
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse
from javascript import require, On, Once

# Import Mineflayer
mineflayer = require('mineflayer')

# --- Configuration ---
MINECRAFT_IP = os.getenv("MINECRAFT_IP", "eleytra.aternos.me")
MINECRAFT_PORT = int(os.getenv("MINECRAFT_PORT", "28657"))
BOT_NAME = os.getenv("BOT_NAME", "Homie")
KOYEB_PORT = int(os.getenv("PORT", "8080"))
PANEL_KEY = os.getenv("PANEL_KEY", "")  # Optional: set to protect the panel

# Global tracking variables
reconnect_delay = 10
bot_instance = None
movement_session = 0           # Incremented each spawn so old movement loops stop
chat_log = deque(maxlen=20)    # Last messages shown on the panel


# --- Web Control Panel ---
class ControlPanelHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed_url.query)
        key = params.get('key', [''])[0]

        # Password check (only if PANEL_KEY is set)
        if PANEL_KEY and key != PANEL_KEY:
            self.send_response(403)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Forbidden: missing or wrong key.")
            return

        key_qs = f"?key={urllib.parse.quote(key)}" if PANEL_KEY else ""

        # Send a chat message / command
        if parsed_url.path == '/send':
            msg = params.get('msg', [''])[0].strip()
            if msg and bot_instance:
                try:
                    bot_instance.chat(msg)
                    print(f"[WEB PANEL] Sent: {msg}")
                    chat_log.append(f">> {msg}")
                except Exception as e:
                    print(f"[WEB PANEL] Failed to send: {e}")
            self.send_response(303)
            self.send_header('Location', '/' + key_qs)
            self.end_headers()
            return

        # Render the panel
        online = bool(bot_instance and getattr(bot_instance, "version", None))
        status = "ONLINE" if online else "CONNECTING/OFFLINE"
        status_class = "online" if online else "offline"
        log_html = "<br>".join(html.escape(line) for line in chat_log) or "No messages yet."
        key_field = f'<input type="hidden" name="key" value="{html.escape(key)}">' if PANEL_KEY else ""

        page = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{html.escape(BOT_NAME)} Control Panel</title>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, sans-serif; background:#121212; color:#e0e0e0; text-align:center; padding:40px 20px; }}
                .card {{ background:#1e1e1e; max-width:560px; margin:0 auto; padding:30px; border-radius:12px; border:1px solid #333; }}
                h1 {{ color:#4caf50; margin-bottom:5px; }}
                .status {{ font-weight:bold; padding:5px 10px; border-radius:5px; background:#333; display:inline-block; margin-bottom:20px; }}
                .online {{ color:#4caf50; }} .offline {{ color:#f44336; }}
                input[type="text"] {{ width:100%; padding:12px; border:1px solid #444; background:#2a2a2a; color:#fff; border-radius:6px; font-size:16px; box-sizing:border-box; }}
                button {{ padding:12px 24px; background:#4caf50; color:#fff; border:none; border-radius:6px; font-size:16px; cursor:pointer; font-weight:bold; }}
                button:hover {{ background:#45a049; }}
                .log {{ text-align:left; background:#111; border:1px solid #333; border-radius:6px; padding:10px; margin-top:20px; font-family:monospace; font-size:13px; max-height:250px; overflow-y:auto; }}
                .hint {{ font-size:13px; color:#888; margin-top:10px; }}
                a {{ color:#4caf50; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>{html.escape(BOT_NAME)} Control Panel</h1>
                <div class="status">Status: <span class="{status_class}">{status}</span></div>

                <form action="/send" method="get">
                    {key_field}
                    <p><input type="text" name="msg" placeholder="Chat message or /command" required autocomplete="off" autofocus></p>
                    <p><button type="submit">Send</button></p>
                </form>
                <div class="hint">Start with <b>/</b> to run a command (bot must be OP), e.g. <code>/gamemode creative {html.escape(BOT_NAME)}</code></div>

                <div class="log">{log_html}</div>
                <p><a href="/{key_qs}">Refresh</a></p>

                <div class="hint">Connected to: <strong>{html.escape(MINECRAFT_IP)}:{MINECRAFT_PORT}</strong></div>
            </div>
        </body>
        </html>
        """
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode('utf-8'))

    def log_message(self, format, *args):
        return


def run_web_server():
    server = HTTPServer(("0.0.0.0", KOYEB_PORT), ControlPanelHandler)
    print(f"[KOYEB] Dashboard panel active on port {KOYEB_PORT}")
    server.serve_forever()


# --- Anti-AFK Random Movement ---
def random_movement(bot, session_id):
    directions = ['forward', 'back', 'left', 'right']
    while session_id == movement_session and bot_instance is bot:
        try:
            action = random.choice(directions)
            jump = random.random() < 0.35

            bot.setControlState(action, True)
            if jump:
                bot.setControlState('jump', True)

            time.sleep(random.uniform(0.3, 1.5))

            bot.setControlState(action, False)
            bot.setControlState('jump', False)

            # Look around a bit
            bot.look(random.uniform(0, 2 * math.pi), random.uniform(-0.5, 0.5), False)

            # Pause between moves
            time.sleep(random.uniform(2, 8))
        except Exception as e:
            print(f"[MOVE] Movement loop stopped: {e}")
            break
    try:
        bot.clearControlStates()
    except Exception:
        pass


# --- Bot Logic ---
def run_bot_once():
    """Connects the bot and blocks until the connection ends."""
    global bot_instance, movement_session

    print(f"[BOT] Attempting connection to {MINECRAFT_IP}:{MINECRAFT_PORT}...")
    disconnected = threading.Event()

    try:
        bot = mineflayer.createBot({
            'host': MINECRAFT_IP,
            'port': MINECRAFT_PORT,
            'username': BOT_NAME,
            'version': '1.21.1',
            'hideErrors': True
        })
        bot_instance = bot
    except Exception as e:
        print(f"[CRITICAL] Client initialization failed: {e}")
        return

    @On(bot, 'spawn')
    def on_spawn(this):
        global reconnect_delay, movement_session
        print(f"[SUCCESS] {BOT_NAME} joined the server!")
        reconnect_delay = 10
        movement_session += 1
        threading.Thread(target=random_movement, args=(bot, movement_session), daemon=True).start()

    @On(bot, 'message')
    def on_message(this, jsonMsg, *args):
        try:
            text = str(jsonMsg.toString())
            if text.strip():
                chat_log.append(text)
        except Exception:
            pass

    @On(bot, 'kicked')
    def on_kick(this, reason, loggedIn):
        print(f"[KICKED] Reason: {reason}")

    @On(bot, 'error')
    def on_error(this, err):
        print(f"[ERROR] {err}")

    @Once(bot, 'end')
    def on_end(this, *args):
        print("[BOT] Link broken.")
        disconnected.set()

    disconnected.wait()
    bot_instance = None


# --- Main Execution ---
if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()

    while True:
        run_bot_once()
        print(f"[RETRY] Waiting {int(reconnect_delay)} seconds before reconnecting...")
        time.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 1.5, 120)
