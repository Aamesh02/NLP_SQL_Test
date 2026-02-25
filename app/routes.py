import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.nlq import ask
from app.exceptions import (
    NLQError,
    SQLGenerationError,
    SQLExecutionError,
    DatabaseConnectionError,
)

logger = logging.getLogger("nlq")

router = APIRouter()


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    elapsed_seconds: float
    sql: str
    rows: list[dict]
    row_count: int


@router.post("/query", response_model=QueryResponse)
async def natural_language_query(req: QueryRequest) -> QueryResponse:
    if not (req.question or "").strip():
        raise HTTPException(status_code=400, detail="question is required and cannot be empty")
    try:
        logger.info("Handling /api/query request.")
        result = await ask(req.question.strip())
    except SQLGenerationError as e:
        raise HTTPException(status_code=422, detail={"type": "sql_generation", "message": e.message, "detail": e.detail})
    except SQLExecutionError as e:
        raise HTTPException(status_code=422, detail={"type": "sql_execution", "message": e.message, "detail": e.detail})
    except DatabaseConnectionError as e:
        raise HTTPException(status_code=503, detail={"type": "database", "message": e.message, "detail": e.detail})
    except NLQError as e:
        raise HTTPException(status_code=500, detail={"type": "nlq", "message": e.message, "detail": e.detail})
    return QueryResponse(
        sql=result["sql"],
        rows=result["rows"],
        row_count=len(result["rows"]),
        elapsed_seconds=result["elapsed_seconds"],
    )
