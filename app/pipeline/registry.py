from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.pipeline.types import Stage
from app.stages.data_quality import DataQualityStage


def build_stages(settings: Settings) -> list[Stage]:
    return [
        DataQualityStage(window_days=settings.return_window_days),
    ]

def build_runner(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> PipelineRunner:
    return PipelineRunner(
        sessionmaker, build_stages(settings), max_attempts=settings.stage_max_attempts
    )
