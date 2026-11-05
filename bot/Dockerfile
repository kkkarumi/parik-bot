FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# texts/ (согласие и политика ПДн) копируется вместе с кодом
COPY . .
# Бот раз в 30 с обновляет этот файл, пока getUpdates доходит до Telegram (heartbeat.py).
# Старше 120 с — контейнер unhealthy: бот завис или нет связи с Telegram/релеем.
ENV BOT_HEARTBEAT_FILE=/tmp/bot-heartbeat
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "import os,sys,time; f=os.environ['BOT_HEARTBEAT_FILE']; sys.exit(0 if os.path.exists(f) and time.time()-os.path.getmtime(f) < 120 else 1)"
CMD ["python", "main.py"]
