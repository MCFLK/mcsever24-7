import os
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse
from javascript import require, On, Once

# Import Mineflayer
mineflayer = require('mineflayer')

# --- Configuration ---
MINECRAFT_IP = os.getenv("MINECRAFT_IP", "eleytra.aternos.me")
MINECRAFT_PORT = int(os.getenv("MINECRAFT_PORT", "28657"))
BOT_NAME = os.getenv("BOT_NAME", "AFK_Bot_Py")
KOYEB_PORT = int(os.getenv("PORT", "8080"))

# Global tracking variables
reconnect_delay = 10
bot_instance = None  # Holds the active bot connection reference

# --- Koyeb Web Control Panel Server ---
class ControlPanelHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global bot_instance
        parsed_url = urllib.parse.urlparse(self.path)
        
        # Check if the user is sending a message via URL parameter (e.g., /send?msg=hello)
        if parsed_url.path == '/send':
            query_params = urllib.parse.parse_qs(parsed_url.query)
            if 'msg' in query_params and bot_instance:
                message_to_send = query_params['msg'][0]
                try:
                    bot_instance.chat(message_to_send)
                    print(f"[WEB PANEL] Sent to server chat: {message_to_send}")
                except Exception as e:
                    print(f"[WEB PANEL] Failed to send chat message: {e}")
            
            # Redirect right back to the home dashboard page after sending
            self.send_response(303)
            self.send_header('Location', '/')
            self.end_headers()
            return

        # Serve the visual Webpage Control Panel
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        
        # Simple HTML Interface
        bot_status = "ONLINE" if bot_instance and bot_instance.version else "CONNECTING/OFFLINE"
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{BOT_NAME} Control Panel</title>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #121212; color: #e0e0e0; text-align: center; padding: 50px 20px; }}
                .card {{ background: #1e1e1e; max-width: 500px; margin: 0 auto; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); border: 1px solid #333; }}
                h1 {{ color: #4caf50; margin-bottom: 5px; }}
                .status {{ font-weight: bold; padding: 5px 10px; border-radius: 5px; background: #333; display: inline-block; margin-bottom: 25px; }}
                .online {{ color: #4caf50; }} .offline {{ color: #f44336; }}
                input[type="text"] {{ width: 80%; padding: 12px; border: 1px solid #444; background: #2a2a2a; color: #fff; border-radius: 6px; font-size: 16px; outline: none; box-sizing: border-box; }}
                button {{ padding: 12px 24px; background: #4caf50; color: #fff; border: none; border-radius: 6px; font-size: 16px; cursor: pointer; font-weight: bold; transition: background 0.2s; }}
                button:hover {{ background: #45a049; }}
                .target {{ font-size: 14px; color: #888; margin-top: 15px; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>{BOT_NAME} Live Chat</h1>
                <div class="status">Status: <span class="{"online" if bot_status == "ONLINE" else "offline"}">{bot_status}</span></div>
                
                <form action="/send" method="get">
                    <p><input type="text" name="msg" placeholder="Type a message to send to Minecraft..." required autocomplete="off" autofocus></p>
                    <p><button type="submit">Send Message</button></p>
                </form>
                
                <div class="target">Connected to: <strong>{MINECRAFT_IP}:{MINECRAFT_PORT}</strong></div>
            </div>
        </body>
        </html>
        """
        self.wfile.write(html_content.encode('utf-8'))

    def log_message(self, format, *args):
        return  # Stop health check spams from bloating Koyeb terminal logs

def run_health_check_server():
    server = HTTPServer(("0.0.0.0", KOYEB_PORT), ControlPanelHandler)
    print(f"[KOYEB] Dashboard panel active on port {KOYEB_PORT}")
    server.serve_forever()

# --- Aggressive Reconnect Bot Logic ---
def launch_minecraft_bot():
    global reconnect_delay, bot_instance
    print(f"[BOT] Attempting connection to {MINECRAFT_IP}:{MINECRAFT_PORT}...")
    
    try:
        bot = mineflayer.createBot({
            'host': MINECRAFT_IP,
            'port': MINECRAFT_PORT,
            'username': BOT_NAME,
            'version': '1.21.1',
            'hideErrors': True
        })
        bot_instance = bot  # Pass instance link to the global reference tracker
    except Exception as e:
        print(f"[CRITICAL] Client initialization failed: {e}")
        handle_reconnect()
        return

    @On(bot, 'spawn')
    def on_spawn(this):
        global reconnect_delay
        print(f"[SUCCESS] {BOT_NAME} successfully joined the server!")
        reconnect_delay = 10
        bot.chat("Connected via Koyeb Remote Panel.")

    @On(bot, 'kicked')
    def on_kick(this, reason, loggedIn):
        print(f"[KICKED] The server kicked the bot. Reason: {reason}")

    @On(bot, 'error')
    def on_error(this, err):
        print(f"[ERROR] Connection failed or interrupted: {err}")

    @Once(bot, 'end')
    def on_disconnect(this):
        global bot_instance
        print("[BOT] Link broken.")
        bot_instance = None  # Clear instance reference
        handle_reconnect()

def handle_reconnect():
    global reconnect_delay
    print(f"[RETRY] Server unstable. Waiting {reconnect_delay} seconds before trying again...")
    time.sleep(reconnect_delay)
    reconnect_delay = min(reconnect_delay * 1.5, 120)
    launch_minecraft_bot()

# --- Main Execution ---
if __name__ == "__main__":
    # Start the custom interactive web control server
    web_thread = threading.Thread(target=run_health_check_server, daemon=True)
    web_thread.start()

    # Launch the physical Minecraft player client
    launch_minecraft_bot()
