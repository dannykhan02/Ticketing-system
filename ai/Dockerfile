# Use lightweight Python image
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source code
COPY . .

# Expose Flask/Gunicorn port
EXPOSE 8080

# Start your app using Gunicorn
CMD ["gunicorn", "app2:app", "--bind", "0.0.0.0:8080", "--timeout", "120", "--workers", "1"]
