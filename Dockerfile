# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Install Node.js (required for the underlying Minecraft client protocol)
RUN apt-get update && apt-get install -y curl \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy and install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the bot script
COPY bot.py .

# Expose the web check port for Koyeb
EXPOSE 8080

# Run the script with unbuffered output so logs show up instantly
CMD ["python", "-u", "bot.py"]
