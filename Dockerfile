FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY safeops ./safeops
COPY api ./api
COPY mcp_server ./mcp_server

ENV SAFEOPS_OLLAMA_BASE_URL=http://host.docker.internal:11434
EXPOSE 8080
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
