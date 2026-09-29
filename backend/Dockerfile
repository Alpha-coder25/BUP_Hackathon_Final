# Backend API + collector — Fuel Supply Intelligence & Resilience Platform
# backend/ is installed as a package (relative imports), run via backend.main:app.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY . ./backend/

EXPOSE 8080
# Collector runs in-process (background thread) unless COLLECTOR_ENABLED=0
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
