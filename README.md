# refund-tollgate

Governed AI refund system. This is step 1: the returns API.

## Run the tests (no Docker needed)

    pip install -e ".[dev]"
    pytest

## Run it for real

    docker compose up -d                      # Postgres + Redis
    python -m app.seed                        # creates tables, prints a customer_id and order_item_id
    uvicorn app.main:create_app --factory --reload

    curl -i -X POST localhost:8000/returns \
      -H "X-Customer-Id: <customer_id>" \
      -H "Idempotency-Key: demo-000001" \
      -H "Content-Type: application/json" \
      -d '{"order_item_id": "<order_item_id>", "reason_text": "The left earcup stopped working after two days."}'

Send the same request again: you get 200 with `Idempotent-Replay: true` and the same return ID.
Interactive docs are at http://localhost:8000/docs.

## Layout

    app/domain/     enums and API schemas (Pydantic)
    app/db/         SQLAlchemy models
    app/services/   business logic, no HTTP types
    app/api/        routes and dependencies
    app/jobs.py     queue protocol, arq implementation, in-memory fake
    tests/          pytest, SQLite in memory

Jobs enqueued by the API are consumed by a worker, which is the next step.
