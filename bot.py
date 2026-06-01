import os
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from javascript import require, On, Once

# Import Mineflayer
mineflayer = require('mineflayer')

# --- Configuration ---
MINECRAFT_IP = os.getenv("MINECRAFT_IP", "eleytra.aternos.me")
MINECRAFT_PORT = int(os.getenv("MINECRAFT_PORT", "28657"))
BOT_NAME = os.getenv("BOT_NAME", "AFK_Bot_Py")
KOYEB_PORT = int(os.getenv("PORT", "8080"))

# Global tracking for reconnection timing
reconnect_delay = 10  # Start by waiting 10 seconds

# --- Koyeb Web Health Check Server ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Python AFK Reconnect Bot is Active.")
    def log_message(self, format, *args):
        return

def run_health_check_server():
    server = HTTPServer(("0.0.0.0", KOYEB_PORT), HealthCheckHandler)
    print(f"[KOYEB] Web server active on port {KOYEB_PORT}")
    server.serve_forever()

# --- Aggressive Reconnect Bot Logic ---
def launch_minecraft_bot():
    global reconnect_delay
    print(f"[BOT] Attempting connection to {MINECRAFT_IP}:{MINECRAFT_PORT}...")
    
    try:
        # Added 'version': '1.21.1' to force protocol matching
        bot = mineflayer.createBot({
            'host': MINECRAFT_IP,
            'port': MINECRAFT_PORT,
            'username': BOT_NAME,
            'version': '1.21.1',  # <-- FORCES BOT TO MATCH YOUR 1.21.1 SERVER
            'hideErrors': True    # Prevents node.js from throwing unhandled stack traces into Koyeb logs
        })
    except Exception as e:
        print(f"[CRITICAL] Client initialization failed: {e}")
        handle_reconnect()
        return

    @On(bot, 'spawn')
    def on_spawn(this):
        global reconnect_delay
        print(f"[SUCCESS] {BOT_NAME} successfully joined the server!")
        reconnect_delay = 10  # Reset the delay timer back to default upon a successful login
        bot.chat("Connected and stabilizing chunks.")

    @On(bot, 'kicked')
    def on_kick(this, reason, loggedIn):
        print(f"[KICKED] The server kicked the bot. Reason: {reason}")

    @On(bot, 'error')
    def on_error(this, err):
        # Catches connection refused, timed out, or DNS issues safely
        print(f"[ERROR] Connection failed or interrupted: {err}")

    @Once(bot, 'end')
    def on_disconnect(this):
        # Using @Once ensures the exit loop is only triggered exactly one time per disconnect event
        print("[BOT] Link broken.")
        handle_reconnect()

def handle_reconnect():
    global reconnect_delay
    print(f"[RETRY] Server unstable. Waiting {reconnect_delay} seconds before trying again...")
    time.sleep(reconnect_delay)
    
    # Exponential backoff: Increase wait time slightly if it keeps failing, topping out at 2 minutes.
    reconnect_delay = min(reconnect_delay * 1.5, 120)
    
    launch_minecraft_bot()

# --- Main Execution ---
if __name__ == "__main__":
    # Start Koyeb's safety web server
    web_thread = threading.Thread(target=run_health_check_server, daemon=True)
    web_thread.start()

    # Kick off the initial connection loop
    launch_minecraft_bot()
