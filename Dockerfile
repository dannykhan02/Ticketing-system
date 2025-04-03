# Use an official Python image that allows package installation
FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Install system dependencies (including zbar)
RUN apt-get update && apt-get install -y libzbar0

# Copy your project files
COPY . .

# Install dependencies (use pip or poetry)
RUN pip install -r requirements.txt

# Command to run the app
CMD ["gunicorn", "app:app"]
