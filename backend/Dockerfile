FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
# Migrate, seed (skipped automatically if data exists), then serve.
CMD ["sh", "-c", "python -m scripts.migrate && python -m scripts.seed && exec gunicorn --bind 0.0.0.0:8000 --workers 2 --threads 8 --access-logfile - wsgi:app"]
