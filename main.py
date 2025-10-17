from flask import Flask
import threading
import bot_code

app = Flask(__name__)

# اجرای کد سیگنال‌دهی در Thread جدا
def run_bot():
    bot_code.main()

threading.Thread(target=run_bot).start()

@app.route('/')
def home():
    return "Bot is running."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
