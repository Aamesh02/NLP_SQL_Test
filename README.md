# Meta Ads NLQ API

Natural language query API over a MySQL database of Meta (Instagram) Ads performance data. Ask questions in plain English; the service converts them to SQL and returns results.

## Setup

1. Copy `.env.example` to `.env` and set:
   - `DATABASE_URL` 
   - `OPENAI_API_KEY`
2. Install: `pip install -r requirements.txt`
3. (Optional) Inspect DB schema and sizes: `python -m scripts.check_db`
4. Run: `uvicorn app.main:app --reload`

## Endpoints

- `GET /ready` — readiness (checks DB)
- `POST /api/query` — body: `{"question": "your question"}` → returns `{ "sql", "rows", "row_count" }`

## Latency

In local tests with this setup:

- Typical questions that scan modest amounts of data return in **~2–2.5 seconds** end-to-end.
- Heavier queries that touch hundreds of rows usually complete in **~4–4.5 seconds**.

Overall the service stays within the **5s** latency target for the kinds of Meta Ads reporting queries it is designed for. Actual numbers will depend on network latency to MySQL and the OpenAI API.
