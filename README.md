# GraphRAG Slack Backend

Production-oriented Python backend scaffold for a GraphRAG pipeline that:

- extracts text from Google Sheets and Google Slides,
- maps each document into graph-friendly metadata with OpenAI,
- stores document relationships in Neo4j, and
- answers Slack `app_mention` events through a FastAPI webhook.

## Project Files

- `config.py`: strongly typed environment settings.
- `ingestion.py`: Google extraction, LLM mapping, and end-to-end ingestion workflow.
- `graph_db.py`: Neo4j driver lifecycle, health checks, and document relationship upserts.
- `engine.py`: GraphRAG query pipeline that reads graph context and synthesizes answers.
- `main.py`: FastAPI application with Slack webhook and health endpoint.

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

## Run The API

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

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
- `POST /ingest/google`: queues a Google Sheets or Slides ingestion job. Requires `X-API-Key`.
- `POST /slack/events`: handles Slack URL verification and `app_mention` events.

## Ingestion Example

Run this from a Python shell or another module:

```python
from ingestion import ingest_google_document

result = ingest_google_document(
    document_id="your-google-file-id",
    title="Quarterly Planning",
    source_type="slides",
)

print(result.metadata.model_dump())
```

Or call the API endpoint:

```bash
curl -X POST http://localhost:8000/ingest/google \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-ingestion-api-token" \
    -d '{"document_id":"your-google-file-id","title":"Quarterly Planning","source_type":"slides"}'
```

## Notes

- `gpt-4o-mini` is used for low-cost metadata extraction.
- `gpt-4o` is used for final Slack answers.
- Slack event handling acknowledges immediately and performs the heavy work in a background task.
- Slack requests are verified with the signing secret before event processing.