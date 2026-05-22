FROM python:3.11-slim

WORKDIR /app

# Install light-server
RUN pip install --no-cache-dir light-server

# Copy model repository and server config
COPY model_repo ./model_repo
COPY server.yaml .

EXPOSE 8000 8001 8002

CMD ["light-server", "serve", "--config", "server.yaml"]
