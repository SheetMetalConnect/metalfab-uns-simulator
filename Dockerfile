FROM python:3.12-slim

WORKDIR /app

# Install the simulator package
COPY pyproject.toml .
COPY src/ src/
COPY config/ config/

RUN pip install --no-cache-dir -e .

ENTRYPOINT ["metalfab-sim"]
CMD ["run", "--broker", "mqtt", "--level", "2"]
