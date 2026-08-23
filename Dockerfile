FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persistentes Config-Verzeichnis
RUN mkdir -p /app/data

# Nicht als root laufen; gosu zum sauberen Privilegien-Abbau nach Rechte-Fix im Entrypoint
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -s /bin/false hlc20 && chown -R hlc20:hlc20 /app \
    && chmod +x entrypoint.sh

EXPOSE 80

ENTRYPOINT ["./entrypoint.sh"]
CMD ["python", "-u", "main.py"]
