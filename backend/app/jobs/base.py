"""JobRunner 介面。

第一版用 FastAPI BackgroundTasks；未來量大要換成 Celery + Redis 時，
只要新增一個 CeleryJobRunner 實作這個介面，services/ 以上完全不用改
（docs/architecture.md 1.6 / 第 7 節）。
"""

import uuid
from abc import ABC, abstractmethod


class JobRunner(ABC):
    @abstractmethod
    async def enqueue(self, job_id: uuid.UUID, document_id: uuid.UUID) -> None:
        """把分析工作排進背景執行，必須立刻回傳，不可以等工作做完。"""

    @abstractmethod
    async def get_status(self, job_id: uuid.UUID) -> str | None:
        """回傳任務目前狀態（PENDING / PROCESSING / COMPLETED / FAILED）。"""
