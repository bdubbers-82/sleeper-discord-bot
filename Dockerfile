# Use a slim Python image (fast + small)
FROM python:3.12-slim

# System deps (add git & tzdata for scheduler timezones)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Environment hygiene
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Ensure New York time available
    TZ=America/New_York

# Workdir
WORKDIR /app

# Copy requirement list first (better Docker layer caching)
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
 && pip install -r requirements.txt

# Copy app source
COPY . /app

# Don’t crash on missing config.json; your bot creates/loads it at runtime
# Expose nothing; Discord uses outgoing connections

# Health-ish check: make sure the file exists so container started correctly
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD python -c "import os,sys; sys.exit(0 if os.path.exists('bot.py') else 1)"

# Start the bot
CMD ["python", "bot.py"]
