class NLQError(Exception):
    """Base for NLQ-related errors."""

    def __init__(self, message: str, detail: str | None = None):
        self.message = message
        self.detail = detail
        super().__init__(message)


class SQLGenerationError(NLQError):
    """LLM failed to produce valid SQL or we couldn't parse it."""


class SQLExecutionError(NLQError):
    """Query ran but DB returned an error."""


class DatabaseConnectionError(NLQError):
    """Could not connect to the database."""
