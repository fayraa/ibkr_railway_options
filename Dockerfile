# Options Bot Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY . .

# Environment variables (set these in Railway)
ENV IBKR_HOST=ib-gateway
ENV IBKR_PORT=4001
ENV PYTHONUNBUFFERED=1

# Run the bot
CMD ["python", "main_v2.py", "run"]
