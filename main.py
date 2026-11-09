"""
Фінальне завдання: вебзастосунок без вебфреймворків + Socket-сервер + MongoDB.

Один файл запускає два окремі процеси:

  1. HTTP-сервер (порт 3000) - віддає сторінки index.html, message.html,
     статичні ресурси style.css та logo.png, а для будь-якого невідомого
     шляху повертає error.html з кодом 404. Дані з форми на message.html
     (POST /message) він пересилає Socket-серверу через UDP-сокет.

  2. Socket-сервер (UDP, порт 5000) - отримує байт-рядок, перетворює його
     на словник і зберігає документ у MongoDB у форматі:
         {"date": "2022-10-29 20:20:58.020261",
          "username": "krabaton",
          "message": "First message"}
     Ключ "date" - час отримання повідомлення (datetime.now()).

Налаштування беруться зі змінних оточення (значення за замовчуванням
підходять для локального запуску; у docker-compose.yaml MONGO_URI вказує
на контейнер mongo).

Запуск:
    python main.py
"""

import logging
import mimetypes
import os
import signal
import socket
import sys
import time
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from multiprocessing import Process
from multiprocessing.connection import wait
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

from pymongo import MongoClient
from pymongo.errors import PyMongoError

BASE_DIR = Path(__file__).resolve().parent
FRONT_DIR = BASE_DIR / "front"  # index.html, message.html, error.html, style.css, logo.png

HTTP_HOST = os.getenv("HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.getenv("HTTP_PORT", "3000"))

# куди вебдодаток пересилає дані (Socket-сервер) і де Socket-сервер слухає
SOCKET_HOST = os.getenv("SOCKET_HOST", "127.0.0.1")
SOCKET_BIND_HOST = os.getenv("SOCKET_BIND_HOST", "0.0.0.0")
SOCKET_PORT = int(os.getenv("SOCKET_PORT", "5000"))

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "chat_db")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "messages")

MAX_BODY_SIZE = 8 * 1024  # байт; запобігає надто великим POST-запитам
UDP_BUFFER_SIZE = 65535

# Маршрути: URL -> файл у папці front. Статичні ресурси перелічені явно,
# тож ніякий інший файл (і вихід за межі папки) недоступний.
PAGE_ROUTES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/message": "message.html",
    "/message.html": "message.html",
}
STATIC_ROUTES = {
    "/style.css": "style.css",
    "/logo.png": "logo.png",
}
FORM_ROUTES = {"/message", "/message.html"}  # куди приймаємо POST з форми


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(processName)s] %(levelname)s: %(message)s",
    )


# ---------------------------------------------------------------------------
# HTTP-сервер
# ---------------------------------------------------------------------------

def forward_to_socket_server(username, message):
    """Пересилає дані форми Socket-серверу через UDP-сокет у вигляді
    байт-рядка формату application/x-www-form-urlencoded."""
    payload = urlencode({"username": username, "message": message}).encode("utf-8")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(payload, (SOCKET_HOST, SOCKET_PORT))


class RequestHandler(BaseHTTPRequestHandler):
    """Обробник запитів: маршрутизація, статика, сторінка 404, форма."""

    server_version = "HomeworkHTTP/1.0"

    def do_GET(self):
        path = urlparse(self.path).path
        filename = PAGE_ROUTES.get(path) or STATIC_ROUTES.get(path)
        if filename is None:
            self.send_not_found()
        else:
            self.send_file(filename, HTTPStatus.OK)

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in FORM_ROUTES:
            self.send_not_found()
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length <= 0:
            self.send_plain(HTTPStatus.BAD_REQUEST, "Порожній запит")
            return
        if length > MAX_BODY_SIZE:
            self.send_plain(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Запит завеликий")
            return

        body = self.rfile.read(length)
        try:
            form = dict(parse_qsl(body.decode("utf-8"), keep_blank_values=True))
        except UnicodeDecodeError:
            self.send_plain(HTTPStatus.BAD_REQUEST, "Некоректне кодування даних")
            return

        username = form.get("username", "").strip()
        message = form.get("message", "").strip()
        if not username or not message:
            self.send_plain(HTTPStatus.BAD_REQUEST, "Потрібні поля username та message")
            return

        try:
            forward_to_socket_server(username, message)
        except OSError as error:
            logging.error("Не вдалося передати дані Socket-серверу: %s", error)
            self.send_plain(HTTPStatus.BAD_GATEWAY, "Socket-сервер недоступний")
            return

        # Post/Redirect/Get: після відправки повертаємо на форму зі статусом
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/message.html?sent=1")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_file(self, filename, status):
        """Віддає файл із папки front з правильним Content-Type."""
        file_path = FRONT_DIR / filename
        try:
            content = file_path.read_bytes()
        except OSError:
            self.send_plain(HTTPStatus.INTERNAL_SERVER_ERROR, f"Файл {filename} недоступний")
            return

        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        if content_type.startswith("text/"):
            content_type += "; charset=utf-8"

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def send_not_found(self):
        """404 Not Found: повертає сторінку error.html."""
        self.send_file("error.html", HTTPStatus.NOT_FOUND)

    def send_plain(self, status, text):
        content = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        logging.info("%s - %s", self.address_string(), format % args)


def run_http_server():
    setup_logging()
    server = ThreadingHTTPServer((HTTP_HOST, HTTP_PORT), RequestHandler)
    logging.info("HTTP-сервер запущено: http://%s:%s", HTTP_HOST, HTTP_PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# ---------------------------------------------------------------------------
# Socket-сервер
# ---------------------------------------------------------------------------

def parse_payload(data):
    """Перетворює отриманий байт-рядок на словник - документ для MongoDB.

    Ключ "date" - час отримання повідомлення (datetime.now())."""
    form = dict(parse_qsl(data.decode("utf-8"), keep_blank_values=True))
    username = form.get("username", "").strip()
    message = form.get("message", "").strip()
    if not username or not message:
        raise ValueError("відсутнє поле username або message")

    return {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        "username": username,
        "message": message,
    }


def connect_to_mongo(retries=30, delay=2):
    """Підключається до MongoDB (з повторними спробами, поки база стартує)
    і повертає колекцію для збереження повідомлень."""
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    for attempt in range(1, retries + 1):
        try:
            client.admin.command("ping")
            logging.info("Підключено до MongoDB (%s)", MONGO_URI)
            return client[MONGO_DB][MONGO_COLLECTION]
        except PyMongoError as error:
            logging.warning("MongoDB недоступна (спроба %s/%s): %s", attempt, retries, error)
            time.sleep(delay)
    raise RuntimeError(f"Не вдалося підключитися до MongoDB ({MONGO_URI})")


def run_socket_server():
    setup_logging()
    collection = connect_to_mongo()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((SOCKET_BIND_HOST, SOCKET_PORT))
        logging.info("Socket-сервер (UDP) слухає %s:%s", SOCKET_BIND_HOST, SOCKET_PORT)
        try:
            while True:
                data, address = sock.recvfrom(UDP_BUFFER_SIZE)
                try:
                    document = parse_payload(data)
                    collection.insert_one(document)
                    logging.info("Збережено повідомлення від '%s'", document["username"])
                except (UnicodeDecodeError, ValueError) as error:
                    logging.warning("Пропущено некоректні дані від %s: %s", address, error)
                except PyMongoError as error:
                    logging.error("Помилка збереження в MongoDB: %s", error)
        except KeyboardInterrupt:
            pass


# ---------------------------------------------------------------------------
# Запуск обох серверів у різних процесах
# ---------------------------------------------------------------------------

def main():
    setup_logging()
    processes = [
        Process(target=run_http_server, name="http-server"),
        Process(target=run_socket_server, name="socket-server"),
    ]
    for process in processes:
        process.start()

    def handle_sigterm(signum, frame):  # docker stop надсилає SIGTERM
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, handle_sigterm)

    exit_code = 0
    try:
        wait([process.sentinel for process in processes])  # доки котрийсь не завершиться
        logging.error("Один із серверів несподівано завершився - зупиняю застосунок")
        exit_code = 1
    except KeyboardInterrupt:
        logging.info("Отримано сигнал зупинки, завершую роботу")
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
        for process in processes:
            process.join(timeout=5)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
