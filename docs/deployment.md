# Deployment Guide — Google Cloud Run

This guide covers deploying the Multi-Agent Research Assistant to Google Cloud Run.

## Prerequisites

| Tool | Minimum Version | Install |
|------|----------------|---------|
| Docker | 24.x | [docs.docker.com](https://docs.docker.com/get-docker/) |
| Google Cloud SDK (`gcloud`) | Latest | [cloud.google.com/sdk](https://cloud.google.com/sdk/docs/install) |
| Python | 3.12 | [python.org](https://www.python.org/) |

## Architecture on Cloud Run

```
┌─────────────────────────────────────────────────┐
│  Google Cloud Run                               │
│                                                 │
│  ┌─────────────────────────────────────────┐   │
│  │  Container (port 8501)                  │   │
│  │  - Streamlit UI                         │   │
│  │  - Workflow Engine                      │   │
│  │  - CrewAI agents (in-process)           │   │
│  │  - ADK RAG agent (in-process)           │   │
│  │  - A2A server (in-process thread)       │   │
│  │  - MCP tools (in-process)               │   │
│  │  - FAISS vector store (in-memory)       │   │
│  │  - SQLite Blackboard (ephemeral disk)   │   │
│  └─────────────────────────────────────────┘   │
│                                                 │
│  Secret Manager: GOOGLE_API_KEY                 │
└─────────────────────────────────────────────────┘
        │
        ▼ external calls
  Google Gemini API (gemini-1.5-flash)
  DuckDuckGo Search API (no key required)
```

> [!WARNING]
> Cloud Run instances are **ephemeral**. SQLite data and FAISS indexes are lost between
> container restarts. For production, use **Cloud SQL** (PostgreSQL) and **Cloud Storage**
> or a managed vector database. See the "Production Considerations" section below.

## Quick Deploy

```bash
# Set required environment variables
export GCP_PROJECT_ID=your-project-id
export GOOGLE_API_KEY=your-google-api-key

# Run the deployment script
chmod +x deployment/cloud_run_deploy.sh
./deployment/cloud_run_deploy.sh
```

## Manual Step-by-Step Deployment

### 1. Authenticate with Google Cloud

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

### 2. Enable Required APIs

```bash
gcloud services enable \
  run.googleapis.com \
  containerregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com
```

### 3. Store API Key in Secret Manager

```bash
# Create secret (first time)
echo -n "YOUR_GOOGLE_API_KEY" | gcloud secrets create google-api-key \
  --data-file=- \
  --replication-policy=automatic

# Or add a new version (subsequent updates)
echo -n "YOUR_GOOGLE_API_KEY" | gcloud secrets versions add google-api-key --data-file=-
```

### 4. Build the Docker Image

```bash
# From the project root directory
docker build -t gcr.io/YOUR_PROJECT_ID/mas-research-assistant:latest .

# Verify build
docker run --rm -p 8501:8501 \
  -e GOOGLE_API_KEY=your-key \
  gcr.io/YOUR_PROJECT_ID/mas-research-assistant:latest
# Open http://localhost:8501 to verify before pushing
```

### 5. Push to Google Container Registry

```bash
gcloud auth configure-docker gcr.io
docker push gcr.io/YOUR_PROJECT_ID/mas-research-assistant:latest
```

### 6. Deploy to Cloud Run

```bash
gcloud run deploy mas-research-assistant \
  --image gcr.io/YOUR_PROJECT_ID/mas-research-assistant:latest \
  --platform managed \
  --region us-central1 \
  --set-secrets=GOOGLE_API_KEY=google-api-key:latest \
  --set-env-vars="APP_ENV=production,LOG_LEVEL=INFO,CREWAI_LLM_MODEL=gemini/gemini-1.5-flash,ADK_MODEL=gemini-1.5-flash" \
  --memory=2Gi \
  --cpu=2 \
  --concurrency=4 \
  --min-instances=0 \
  --max-instances=3 \
  --port=8501 \
  --timeout=300 \
  --allow-unauthenticated
```

### 7. Get the Service URL

```bash
gcloud run services describe mas-research-assistant \
  --region us-central1 \
  --format 'value(status.url)'
```

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOOGLE_API_KEY` | ✅ Yes | — | Google Gemini API key (via Secret Manager) |
| `CREWAI_LLM_MODEL` | No | `gemini/gemini-1.5-flash` | LiteLLM model string for CrewAI |
| `ADK_MODEL` | No | `gemini-1.5-flash` | Model name for Google ADK |
| `LLM_TEMPERATURE` | No | `0.2` | LLM sampling temperature |
| `APP_ENV` | No | `development` | `development` or `production` |
| `LOG_LEVEL` | No | `INFO` | Python log level |
| `MAX_CONCURRENT_AGENTS` | No | `4` | Max parallel agent threads |
| `CHUNK_SIZE` | No | `500` | RAG chunk size in tokens |
| `RAG_TOP_K` | No | `5` | Number of RAG results |
| `EMBEDDING_MODEL` | No | `all-MiniLM-L6-v2` | Sentence-transformer model |

## Monitoring and Logs

```bash
# Stream live logs
gcloud run services logs tail mas-research-assistant --region us-central1

# Last 50 log entries
gcloud run services logs read mas-research-assistant \
  --region us-central1 \
  --limit 50

# View metrics in Cloud Console
# https://console.cloud.google.com/run/detail/us-central1/mas-research-assistant/metrics
```

## Updating the Deployment

```bash
# Rebuild and redeploy after code changes
docker build -t gcr.io/YOUR_PROJECT_ID/mas-research-assistant:latest .
docker push gcr.io/YOUR_PROJECT_ID/mas-research-assistant:latest
gcloud run deploy mas-research-assistant \
  --image gcr.io/YOUR_PROJECT_ID/mas-research-assistant:latest \
  --region us-central1
```

## Rolling Back

```bash
# List revisions
gcloud run revisions list --service mas-research-assistant --region us-central1

# Route all traffic to a previous revision
gcloud run services update-traffic mas-research-assistant \
  --region us-central1 \
  --to-revisions REVISION_NAME=100
```

## Production Considerations

### Persistent Storage
Cloud Run containers have ephemeral local storage. For production:

| Component | Dev (Current) | Production Recommendation |
|-----------|--------------|--------------------------|
| Blackboard | SQLite on local disk | Cloud SQL (PostgreSQL) |
| Vector Store | FAISS in-memory | Vertex AI Vector Search or Pinecone |
| Uploaded Documents | Local `data/uploads/` | Google Cloud Storage |
| Session Data | In-memory dict | Cloud Memorystore (Redis) |

### Scaling
- Set `--min-instances=1` to eliminate cold-start latency for the Streamlit UI
- `--concurrency=4` matches `MAX_CONCURRENT_AGENTS` setting
- Sentence-transformer model downloads on first start (~90 MB); pre-warm or bake into image

### Security
- Enable Cloud Armor for DDoS protection
- Use Cloud IAP for authentication instead of `--allow-unauthenticated`
- Store all secrets in Secret Manager, never in container image
- Enable VPC Connector if Gemini API calls need to route through your VPC

### Cost Optimization
- Use `--min-instances=0` (scale to zero) for non-production environments
- `gemini-1.5-flash` is significantly cheaper than `gemini-1.5-pro`; use Pro only for synthesis if needed
- Set `EVAL_MAX_TOKENS_PER_RUN` to cap evaluation costs

## Dockerfile Notes

The [`Dockerfile`](../Dockerfile) uses:
- `python:3.12-slim` base image
- Non-root user (`masuser`) for security
- Layer caching (requirements first, then code)
- Health check via Streamlit's built-in health endpoint
- `libgomp1` for FAISS OpenMP support

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Container exits immediately | Missing `GOOGLE_API_KEY` | Check Secret Manager binding |
| `ModuleNotFoundError` | Package not in requirements.txt | Add and rebuild |
| FAISS index lost on restart | Ephemeral storage | Use Cloud Storage mount or rebuild index from stored documents |
| Slow first response | Sentence-transformer download | Pre-warm instance or increase `--start-period` in healthcheck |
| Timeout on evaluation runs | 300s limit | Reduce `--limit` in harness or increase `--timeout` |

