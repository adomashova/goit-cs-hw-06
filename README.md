# goit-cs-hw-06

Фінальне завдання курсу: вебзастосунок **без вебфреймворків**, який через
сокети передає дані з форми в MongoDB. Усе розгортається в Docker.

```
браузер ──HTTP :3000──▶ HTTP-сервер ──UDP :5000──▶ Socket-сервер ──▶ MongoDB
         (форма)         (процес 1)     (байт-рядок)    (процес 2)      (том)
```

## Структура репозиторію

```
goit-cs-hw-06/
├── main.py               # HTTP-сервер і Socket-сервер у двох окремих процесах
├── front/
│   ├── index.html        # головна сторінка
│   ├── message.html      # сторінка з формою
│   ├── error.html        # сторінка 404
│   ├── style.css         # стилі
│   └── logo.png          # логотип
├── Dockerfile            # образ вебзастосунку
├── docker-compose.yaml   # застосунок + MongoDB + том для даних
├── requirements.txt
├── .dockerignore
├── .gitignore
└── README.md
```

## Як це працює

- **HTTP-сервер** (порт `3000`, `http.server` зі стандартної бібліотеки)
  - `/`, `/index.html` → `index.html`; `/message`, `/message.html` → `message.html`;
  - статика: `/style.css`, `/logo.png`;
  - будь-який інший шлях → сторінка `error.html` зі статусом `404 Not Found`;
  - `POST /message` (форма) → дані пересилаються Socket-серверу через
    UDP-сокет, браузер отримує редирект на `/message.html?sent=1`
    (там показується повідомлення про успіх).
- **Socket-сервер** (UDP, порт `5000`) отримує байт-рядок
  (`username=...&message=...`), перетворює його на словник і зберігає
  документ у MongoDB (база `chat_db`, колекція `messages`):

```json
{
  "date": "2026-11-08 20:17:49.814690",
  "username": "krabaton",
  "message": "First message"
}
```

  Ключ `date` — час отримання повідомлення (`datetime.now()`).
- `main.py` запускає обидва сервери як **окремі процеси**
  (`multiprocessing.Process`); якщо один із них падає — застосунок
  завершується (Docker його перезапустить), на `SIGTERM` (`docker stop`)
  обидва процеси зупиняються коректно.
- Дані MongoDB лежать у **Docker volume** `mongo_data`, а не всередині
  контейнера, тому переживають `docker compose down` і перестворення
  контейнерів.

> Час у документах — час всередині контейнера (UTC).

## Запуск у Docker (основний спосіб)

З кореня репозиторію:

```bash
docker compose up --build
```

(або `docker-compose up --build` у старих версіях Docker). Перший запуск
збирає образ і завантажує `mongo:7`. Застосунок стартує лише після того, як
MongoDB пройде healthcheck.

Далі відкрийте **http://localhost:3000**:

1. Головна сторінка з логотипом і стилями.
2. «Надіслати повідомлення» → заповніть ім'я та текст → «Надіслати» →
   з'явиться зелене повідомлення про успіх.
3. Відкрийте неіснуючу адресу, наприклад http://localhost:3000/abc —
   побачите сторінку `error.html` (404).

У логах (`docker compose logs -f app`) буде щось на кшталт:

```
[http-server] INFO: HTTP-сервер запущено: http://0.0.0.0:3000
[socket-server] INFO: Підключено до MongoDB (mongodb://mongo:27017)
[socket-server] INFO: Socket-сервер (UDP) слухає 0.0.0.0:5000
[socket-server] INFO: Збережено повідомлення від 'krabaton'
```

### Перевірити дані в MongoDB

```bash
docker compose exec mongo mongosh --quiet --eval 'db.getSiblingDB("chat_db").messages.find().toArray()'
```

### Перевірити, що дані зберігаються у volume

```bash
docker compose down          # зупиняє й видаляє контейнери (том лишається)
docker compose up -d         # знову піднімає
docker compose exec mongo mongosh --quiet --eval 'db.getSiblingDB("chat_db").messages.countDocuments()'
```

Кількість повідомлень не змінилась. Щоб видалити й дані — `docker compose down -v`.

## Локальний запуск без Docker (необов'язково)

Потрібен запущений MongoDB на `localhost:27017` і Python 3.9+:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

Налаштування змінюються змінними оточення: `HTTP_PORT`, `SOCKET_PORT`,
`SOCKET_HOST`, `MONGO_URI`, `MONGO_DB`, `MONGO_COLLECTION`.

## Завантаження на GitHub

Репозиторій: https://github.com/adomashova/goit-cs-hw-06

```bash
git init
git add .
git commit -m "Фінальне завдання: вебзастосунок із сокетами, MongoDB та Docker"
git branch -M main
git remote add origin https://github.com/adomashova/goit-cs-hw-06.git
git push -u origin main
```

Якщо git ще не знає, хто ти:

```bash
git config --global user.name "adomashova"
git config --global user.email "29256351+adomashova@users.noreply.github.com"
```

Якщо GitHub попросить пароль при `git push` — введи **Personal Access
Token** (не пароль від акаунта). Якщо репозиторій на GitHub уже не порожній
і `push` видасть помилку про розбіжність історій:

```bash
git pull origin main --allow-unrelated-histories
git push -u origin main
```
