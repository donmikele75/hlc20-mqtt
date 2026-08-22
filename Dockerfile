FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persistentes Config-Verzeichnis
RUN mkdir -p /app/data

# Nicht als root laufen
RUN useradd -r -s /bin/false hlc20 && chown -R hlc20:hlc20 /app
USER hlc20

EXPOSE 80

CMD ["python", "-u", "main.py"]
