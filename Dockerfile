FROM python:3.11-slim

# System packages needed for Playwright + Chromium
RUN apt-get update && apt-get install -y \
    wget gnupg ca-certificates curl unzip fonts-liberation \
    libnss3 libatk-bridge2.0-0 libxss1 libasound2 libxcomposite1 \
    libxrandr2 libgtk-3-0 libgbm-dev libxshmfence-dev \
    && apt-get clean

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install playwright && playwright install chromium

COPY . .

CMD ["python", "main.py"]