# About author
I started in data science trying to build models, realized the real bottleneck was always the data itself, and moved into data engineering. That shift taught me how to build systems that actually scale. Now, as a Principal Data Consultant, I help organizations architect and implement data solutions — from platforms and pipelines to complete data-driven applications. I have the full-stack skills to ship end-to-end when needed, but my real passion is in the data engineering layer.

contact info and feedback

linkedin : https://www.linkedin.com/in/kayyasit-sookma-96b893141/ 
email : tearteamoguy@gmail.com

# GraphRAG Slack Backend

Production-oriented Python backend scaffold for a GraphRAG pipeline that:

- extracts text from Google Sheets, Google Slides, and Google Docs,
- maps each document into graph-friendly metadata with OpenAI,
- stores document relationships in Neo4j, and
- answers Slack `app_mention` events through a FastAPI webhook.

## Project Files

- `config.py`: strongly typed environment settings.
- `ingestion.py`: Google extraction, LLM mapping, and end-to-end ingestion workflow.
- `graph_db.py`: Neo4j driver lifecycle, health checks, and document relationship upserts.
- `engine.py`: GraphRAG query pipeline that reads graph context and synthesizes answers.
- `main.py`: FastAPI application with Slack webhook and health endpoint.
- `app/`: modular package entrypoints (`app/api`, `app/core`, `app/services`) for container/runtime imports.
- `tests/`: all automated tests and smoke checks.

## Setup

1. Create and activate a Python 3.11+ virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and fill in real credentials.
4. Place your Google service account JSON at the configured `GOOGLE_CREDENTIALS_FILE_PATH`.
5. Ensure the service account has access to the target Google Sheets and Slides files.
6. Set a strong `INGESTION_API_TOKEN` for the ingestion endpoint.
7. Configure Slack to send signed requests using your `SLACK_SIGNING_SECRET`.
8. If you use OpenRouter, set `OPENAI_BASE_URL=https://openrouter.ai/api/v1` and choose OpenRouter model IDs.

## Local Dev Stack (Neo4j + Ollama)

This project supports explicit runtime modes via `APP_ENV`:

- `dev` -> reads `.env.dev` (or falls back to `.env`)
- `prod` -> reads `.env.prod` (or falls back to `.env`)

### 1. Start local infrastructure with Docker

```bash
docker compose -f docker-compose.local.yml up -d
```

To run API + Neo4j + Ollama in one command:

```bash
docker compose -f docker-compose.local.yml up -d --build
```

This starts:

- Neo4j local at `bolt://127.0.0.1:7687` with:
    - user: `neo4j`
    - password: `neo4jforlocal`
- Ollama local at `http://127.0.0.1:11434`

### 2. Pull a reasonable local model

For simple GraphRAG-style Q&A, use `llama3.2:3b`:

```bash
docker exec -it kg-ollama-local ollama pull llama3.2:3b
```

### 3. Create your environment files

Unix/macOS:

```bash
cp .env.dev.example .env.dev
cp .env.prod.example .env.prod
```

PowerShell:

```powershell
Copy-Item .env.dev.example .env.dev
Copy-Item .env.prod.example .env.prod
```

` .env.dev.example` is pre-configured for local Neo4j + local Ollama.

### 4. Start API explicitly in dev or prod mode

Development mode (local only):

```bash
python run_app.py --env dev --host 127.0.0.1 --port 8001 --reload
```

Production-like mode (local machine):

```bash
python run_app.py --env prod --host 0.0.0.0
```

If `PORT` is not set locally, `run_app.py` defaults to `8001`.

## Deploy On Render

For Render Web Service deployment, use production mode and let Render provide the port dynamically.

Render settings:

1. Runtime: Python
2. Build command:

```bash
pip install -r requirements.txt
```

3. Start command (recommended):

```bash
uvicorn app.api.asgi:app --host 0.0.0.0 --port $PORT
```

Alternative start command via runner:

```bash
python run_app.py --env prod --host 0.0.0.0
```

Required Render environment variable:

- `APP_ENV=prod`

Set these secrets in Render Environment Variables (do not commit in repo):

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_SMALL_MODEL`
- `OPENAI_LARGE_MODEL`
- `NEO4J_URI`
- `NEO4J_USER`
- `NEO4J_PASSWORD`
- `SLACK_BOT_TOKEN`
- `SLACK_SIGNING_SECRET`
- `GOOGLE_CREDENTIALS_FILE_PATH`
- `INGESTION_API_TOKEN`

After deploy, update Slack Events Request URL to:

- `https://<your-render-domain>/slack/events`

## Run The API Locally

```bash
uvicorn app.api.asgi:app --host 127.0.0.1 --port 8001
```

Use this fixed `8001` command for local development only.
For hosted production (Render), use dynamic port binding (`$PORT`) from the deploy section above.

## Public API Requirement (Prod-Ready)

If Slack Events or external clients must call this API, your service must be reachable from the public internet.

Use one of these options:

1. Host the API on a cloud platform (recommended for production).
2. Deploy behind a reverse proxy/load balancer with HTTPS.
3. For temporary testing only, expose local port `8001` using VS Code port forwarding / dev tunnel.

### Why this is required

- Slack cannot call `localhost` directly.
- Webhooks and external integrations need a public URL such as `https://your-domain/slack/events`.

### Production checklist for public exposure

1. Use HTTPS only (TLS certificate).
2. Restrict CORS and inbound access rules.
3. Keep secrets in environment/secret manager (never hardcode in repo).
4. Rotate `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, and API keys if leaked.
5. Run health checks and centralized logging.
6. Put the app behind a gateway/proxy and rate limiting.

### Temporary local exposure (development only)

If you do not have hosting yet, forward local port `8001` publicly using VS Code Ports or a dev tunnel, then set Slack Request URL to:

`https://<your-public-url>/slack/events`

Do not treat forwarded local URLs as long-term production infrastructure.

## OpenRouter Configuration

For native OpenAI, keep `OPENAI_BASE_URL` empty and use the default model names.

For OpenRouter, use values like:

```env
OPENAI_API_KEY=your-openrouter-key
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_SMALL_MODEL=openai/gpt-4o-mini
OPENAI_LARGE_MODEL=openai/gpt-4o
```

## Endpoints

- `GET /health`: verifies API readiness and Neo4j connectivity.
- `POST /ingest/google`: queues a Google Sheets, Slides, or Docs ingestion job. Requires `X-API-Key`.
- `POST /ingest/text`: queues direct raw text ingestion. Requires `X-API-Key`.
- `POST /query`: returns a synchronous GraphRAG answer text for an HTTP question.
- `POST /slack/events`: handles Slack URL verification and `app_mention` events.

## Prompt Engineering

Use these code locations to tune behavior and instructions:

- Ingestion metadata prompt: `ingestion.py` in `map_document_structure(...)`.
    This controls category style, summary shape, and related topic extraction.
- Answering system prompt: `engine.py` in `query_graph_rag(...)`.
    This controls how strictly answers follow graph evidence, tone, and uncertainty handling.
- Output length and cost: `MAX_QUERY_COMPLETION_TOKENS` in `engine.py`.

Recommended approach:

1. Keep ingestion prompt focused on consistent structure extraction.
2. Keep query prompt focused on factual, graph-grounded answers.
3. Test by ingesting a sample then calling `POST /query` with representative questions.

Example query request:

```json
{
    "question": "Summarize the main documents in the graph."
}
```

Example query response:

```json
{
    "status": "ok",
    "answer": "..."
}
```

## Slack Usage

- Mention the bot with a real question to query the graph context.
- Mention the bot by itself, or with `help`, `usage`, `examples`, or `suggestions`, to get a short onboarding message plus suggested questions.
- Suggested questions are derived from the current graph content and the local project documentation.

## Standalone Slack Script

Use `slack_handler.py` when you need reusable Slack webhook functions outside the FastAPI app:

- `send_slack_webhook_message(...)`: sends through an Incoming Webhook URL.
- `send_slack_bot_message(...)`: sends through Slack `chat.postMessage`.
- `receive_slack_webhook(...)`: validates signature and parses incoming webhook payloads.

CLI examples:

```bash
python slack_handler.py send-webhook \
    --webhook-url "https://hooks.slack.com/services/XXX/YYY/ZZZ" \
    --text "Hello from webhook"
```

```bash
python slack_handler.py send-bot \
    --bot-token "xoxb-..." \
    --channel "C0123456789" \
    --text "Hello from bot token"
```

```bash
python slack_handler.py verify \
    --signing-secret "your-signing-secret" \
    --timestamp "1234567890" \
    --signature "v0=..." \
    --body '{"type":"event_callback","event":{"type":"app_mention"}}'
```

## Ingestion Example

Run this from a Python shell or another module:

```python
from ingestion import ingest_google_document

result = ingest_google_document(
    document_id="your-google-file-id",
    title="Quarterly Planning",
    source_type="doc",
)

print(result.metadata.model_dump())
```

Or call the local API endpoint:

```bash
curl -X POST http://localhost:8001/ingest/google \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-ingestion-api-token" \
    -d '{"document_id":"your-google-file-id","title":"Quarterly Planning","source_type":"doc"}'
```

Direct text ingestion (no Google API call, local example):

```bash
curl -X POST http://localhost:8001/ingest/text \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-ingestion-api-token" \
    -d '{"document_id":"manual-note-001","title":"Manual Context","text":"Paste your context text here."}'
```

Local file ingestion script:

```bash
python ingest_local_file.py \
    --file "KGdatasolution Company Profile & History.txt" \
    --title "KGdatasolution Company Profile & History"
```

Optional arguments:

- `--document-id`: set your own stable document id.
- `--base-url`: target another API base URL (default `http://127.0.0.1:8001`).
- `--api-key`: pass ingestion token directly instead of reading from `.env`.

Remote forward smoke test (dev tunnel):

```bash
python tests/ingestion_forward_check.py \
    --base-url "https://3554qlgx-8001.asse.devtunnels.ms/"
```

This sends a `POST /ingest/text` request with your `INGESTION_API_TOKEN` and verifies whether the remote API accepts ingestion.

## Notes

- `gpt-4o-mini` is used for low-cost metadata extraction.
- `gpt-4o` is used for final Slack answers.
- Slack event handling acknowledges immediately and performs the heavy work in a background task.
- Slack requests are verified with the signing secret before event processing.

## Live Integration Tests (Real Slack Token)

Use this when you want a real-network Slack verification instead of mocked tests.

1. Ensure `.env` contains valid `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET`.
2. Set a real channel ID in `SLACK_TEST_CHANNEL_ID` (for example `C0123456789`).
3. Enable live tests with `RUN_LIVE_SLACK_TESTS=1`.

PowerShell example:

```powershell
$env:RUN_LIVE_SLACK_TESTS = "1"
$env:SLACK_TEST_CHANNEL_ID = "C0123456789"
python -m unittest -q tests.test_live_integration
```

Run moved test suite from the `tests/` folder:

```bash
python -m unittest -q tests.test_main tests.test_engine tests.test_integration
```

Live test path (when enabled):

```bash
python -m unittest -q tests.test_live_integration
```

The live suite validates:

- Sending a real message through Slack `chat.postMessage` with `send_slack_bot_message(...)`.
- Hitting `/slack/events` with a valid Slack signature to verify request signing and event routing.