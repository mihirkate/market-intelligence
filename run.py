import uvicorn

from app.core.config import settings
from app.core.logging import configure_logging, get_logger


def main() -> None:
    """Start the FastAPI application."""
    settings.ensure_directories()
    configure_logging()

    logger = get_logger(__name__)
    logger.info("Storage Ready")
    logger.info("API Bootstrap")

    uvicorn.run(
        "app.api.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
