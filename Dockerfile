# Container image for the Insight Copilot app — for Cloud Run / App Runner /
# Azure Container Apps / Render / Fly.io / any Docker host.
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (better layer caching).
COPY requirements.txt insight_copilot/requirements.txt ./insight_copilot/requirements.txt
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code.
COPY . .

# Most managed hosts inject the port to listen on via $PORT (default 8501 locally).
ENV PORT=8501
EXPOSE 8501

# Provide the API key at runtime as an env var, e.g.:
#   docker run -e OPENROUTER_API_KEY=sk-or-... -p 8501:8501 insight-copilot
CMD ["sh", "-c", "streamlit run streamlit_app.py --server.port=${PORT} --server.address=0.0.0.0"]
