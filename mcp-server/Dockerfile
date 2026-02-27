FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/

ENV MQTT_BROKER=mqtt
ENV MQTT_PORT=1883

CMD ["python", "src/metalfab_mcp_server.py"]
