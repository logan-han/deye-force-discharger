FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY deye_client.py .
COPY weather_client.py .
COPY app.py .
COPY templates/ ./templates/

# Config is provided via volume mount in docker-compose.yml

# Expose port
EXPOSE 7777

# Set timezone (can be overridden via environment variable)
ENV TZ=Australia/Sydney

# Run the application
CMD ["python", "app.py"]
