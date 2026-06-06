FROM python:3.11-slim

# Prevent writing compiled .pyc files
ENV PYTHONDONTWRITEBYTECODE=1
# Enforce raw stdout/stderr printing without buffering
ENV PYTHONUNBUFFERED=1

WORKDIR /compliance_app

# Install standard gcc/system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install packages
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Provision headless browser drivers for crawler
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy active workspace files
COPY . .

EXPOSE 8000

# Execute server boot using uvicorn
CMD ["uvicorn", "compliance_engine.server:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
