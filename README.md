# llmapp09 — Multi-Route LLM Text Analysis API

A FastAPI text-analysis service that routes each NLP task to a different LLM,
with input/output guardrails, local metrics, Langfuse tracing, a Flask UI,
containers, CI and Kubernetes manifests.

## Components

| Path | What it is |
|------|------------|
| `llm-multiroute/` | Main FastAPI backend. One model per task, guardrails, metrics, Langfuse tracing. Port 8080 |
| `llm-frontend-python/` | Flask UI that calls the backend. Port 5000 |
| `llm-python/` | Simpler single-model variant of the backend (not part of the Docker stack) |
| `deepeval-tests/` | DeepEval quality evaluations against a running backend |
| `promptfoo-tests/` | Promptfoo YAML suites against a running backend |
| `.github/workflows/` | Lint → test → Docker build/scan/push pipelines |

## API

All endpoints are under `/api/ai`. Swagger UI: `http://localhost:8080/swagger-ui.html`
(OpenAPI JSON at `/api-docs`).

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/ai/classify` | Labels, tags, primary category |
| POST | `/api/ai/sentiment` | Sentiment, score, emotions |
| POST | `/api/ai/summarize` | Summary, key points, word count |
| POST | `/api/ai/intent` | Primary/secondary intent, category |
| GET | `/api/ai/routes` | Which model serves each task |
| GET | `/api/ai/guardrails` | Active guardrails and blocking config |
| GET | `/api/ai/metrics/cost` | Token usage records and totals |
| GET | `/api/ai/metrics/performance` | Latency records with p50/p95/avg |
| GET | `/api/ai/metrics/safety` | Prompt injection / policy / PII events |

```bash
curl -X POST http://localhost:8080/api/ai/classify \
  -H 'Content-Type: application/json' \
  -d '{"text": "The central bank raised interest rates today."}'
```

## Configuration

Copy `llm-multiroute/.env.example` to `.env` and fill it in. `.env` is
gitignored — never commit real keys.

| Variable | Default | Purpose |
|----------|---------|---------|
| `OLLAMA_API_KEY` | — | Ollama Cloud API key |
| `OLLAMA_BASE_URL` | `https://ollama.com` | LLM endpoint |
| `OLLAMA_TEMPERATURE` | `0.7` | Sampling temperature |
| `OLLAMA_MODEL_CLASSIFY` | `gemma4:31b` | Model for classify |
| `OLLAMA_MODEL_SENTIMENT` | `glm-5.2` | Model for sentiment |
| `OLLAMA_MODEL_SUMMARIZE` | `mistral-large-3:675b` | Model for summarize |
| `OLLAMA_MODEL_INTENT` | `minimax-m3` | Model for intent |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | — | Langfuse credentials |
| `LANGFUSE_HOST` | — | e.g. `https://us.cloud.langfuse.com`. `LANGFUSE_BASE_URL` is accepted as an alias |
| `LANGFUSE_TRACING_ENVIRONMENT` | `development` | Tags traces as development/staging/production |
| `LANGFUSE_TRACING_ENABLED` | `true` | Set `false` to disable tracing |
| `APP_VERSION` | `1.0.0` | Recorded on every trace |
| `GUARDRAILS_BLOCK_PROMPT_INJECTION` | `false` | Reject offending requests with HTTP 400 instead of only logging |
| `GUARDRAILS_BLOCK_HARMFUL_CONTENT` | `false` | As above, for harmful content |
| `GUARDRAILS_BLOCK_SECRETS` | `false` | As above, for detected secrets |

PII is always redacted before the text reaches the model, never blocked.

## Run with Docker (recommended)

```bash
docker compose up --build
```

- Backend: http://localhost:8080/swagger-ui.html
- Frontend: http://localhost:5000

On macOS, port 5000 is often taken by AirPlay Receiver — either turn it off in
System Settings → General → AirDrop & Handoff, or map another host port.

Build and publish images by hand:

```bash
docker build -t bdarwin/llm-multiroute:latest llm-multiroute
docker build -t bdarwin/llm-frontend-python:latest llm-frontend-python
docker login -u bdarwin
docker push bdarwin/llm-multiroute:latest
docker push bdarwin/llm-frontend-python:latest
```

See `docker_readme.md` for image details.

## Run locally without Docker

```bash
# Backend
cd llm-multiroute
pip install -r requirements.txt          # or: uv run --with-requirements requirements.txt
uvicorn app.main:app --port 8080 --reload

# Frontend (separate terminal)
cd llm-frontend-python
pip install -r requirements.txt
python app.py
```

`guardrails-ai` sends anonymous telemetry to its own endpoint, which shows up as
connection errors when offline. The container images disable it; locally run
`guardrails configure --disable-metrics`.

## Tests and evaluations

```bash
cd llm-multiroute && pytest -q          # unit tests, no network or API keys needed
```

The evaluation suites need a backend running on port 8080:

```bash
cd deepeval-tests  && pytest -q         # DeepEval quality metrics (LLM judge)
cd promptfoo-tests && npx promptfoo eval -c classify.yaml
```

Unit tests never emit Langfuse traces: `tests/conftest.py` sets
`LANGFUSE_TRACING_ENABLED=false` so mocked runs don't pollute the project.

## Observability

Every API request is one Langfuse trace named after its task
(`classify-text`, `sentiment-text`, …), containing:

- a root span whose input is the guarded text and output the validated result
- a `guardrail` observation (`guard-input`) recording redaction/blocking
- a `generation` (`llm-generate`) with model, temperature, token usage and latency
- trace tags (`task:<type>`, `api`), app version and environment
- boolean scores: `guardrail-blocked`, `input-redacted`

Only redacted text is sent to Langfuse, so detected PII and secrets stay local.
Local metrics remain available through the `/api/ai/metrics/*` endpoints.
See `langfuse.md` for setup and what to look at in the UI.

## CI/CD

Four workflows in `.github/workflows/`, each triggered by changes to its own
directory: lint (Ruff) → unit tests (pytest) → Docker build → Trivy scan →
push to Docker Hub on the default branch. Details in `workflow_readme.md`.

Repository settings the pipeline expects:

- Secret `DOCKERHUB_TOKEN` — a Docker Hub access token
- Variable `DOCKERHUB_USERNAME` — optional; defaults to `bdarwin`

`.trivyignore` lists accepted CVEs with no upstream fix.

## Kubernetes

`llm-multiroute/k8s/deployment.yaml` provides a namespace, ConfigMap, Secret,
Deployment and Service. Fill the Secret with base64 values before applying:

```bash
echo -n 'your-api-key' | base64
kubectl apply -f llm-multiroute/k8s/deployment.yaml
```

See `llm-multiroute/kubernetes_deployment.md`.
