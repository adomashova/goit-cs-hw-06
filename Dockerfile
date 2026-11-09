FROM python:3.12-slim

# вивід логів одразу, без буферизації (видно в `docker compose logs`)
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY front ./front

# HTTP-сервер (TCP) та Socket-сервер (UDP)
EXPOSE 3000
EXPOSE 5000/udp

CMD ["python", "main.py"]
