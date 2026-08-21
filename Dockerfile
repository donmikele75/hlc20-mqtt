FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY hlc20_mqtt.py .

# Nicht als root laufen
RUN useradd -r -s /bin/false hlc20
USER hlc20

CMD ["python", "-u", "hlc20_mqtt.py"]
