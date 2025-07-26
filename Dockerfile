FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget unzip curl gnupg chromium chromium-driver \
    fonts-liberation libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdbus-1-3 \
    libgdk-pixbuf2.0-0 libxcomposite1 libxrandr2 libxdamage1 libxss1 libasound2 \
    libxshmfence1 libgbm1 libgtk-3-0 xvfb \
    && rm -rf /var/lib/apt/lists/*

ENV DRIVER_PATH=/usr/bin/chromedriver
ENV BROWSER_BIN=/usr/bin/chromium

# Add non-root user
RUN useradd -m botuser
WORKDIR /app
COPY . /app
RUN chown -R botuser:botuser /app

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Switch to non-root user
USER botuser

# Use the wrapper script instead of bot.py directly
CMD ["python", "run.py"]
