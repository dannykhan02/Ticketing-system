FROM python:3.11-slim

# Install necessary libraries
RUN apt-get update && apt-get install -y \
    libzbar0 \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy project files
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose the app port (if necessary)
EXPOSE 8000

# Run the app
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "app:app"]
