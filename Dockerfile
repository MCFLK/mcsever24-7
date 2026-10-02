FROM node:20-slim

RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --break-system-packages -r requirements.txt

RUN npm install mineflayer

COPY . .

ENV PORT=8080
EXPOSE 8080

CMD ["python3", "bot.py"]
