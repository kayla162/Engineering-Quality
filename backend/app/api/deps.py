"""FastAPI 相依注入。router 只透過這裡取得 service，不自己組裝。"""

from typing import Annotated

from fastapi import BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.jobs.background_runner import BackgroundTasksJobRunner
from app.services.document_service import DocumentService
from app.services.job_service import JobService
from app.services.reference_service import ReferenceService
from app.services.regulation_service import RegulationService
from app.services.report_service import ReportService

DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_document_service(session: DbSession) -> DocumentService:
    return DocumentService(session)


def get_reference_service(session: DbSession) -> ReferenceService:
    return ReferenceService(session)


def get_regulation_service(session: DbSession) -> RegulationService:
    return RegulationService(session)


def get_report_service(session: DbSession) -> ReportService:
    return ReportService(session)


def get_job_service(session: DbSession, background_tasks: BackgroundTasks) -> JobService:
    # 要換成 Celery 時，只需要在這裡換成 CeleryJobRunner()
    return JobService(session, BackgroundTasksJobRunner(background_tasks))


DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]
ReferenceServiceDep = Annotated[ReferenceService, Depends(get_reference_service)]
RegulationServiceDep = Annotated[RegulationService, Depends(get_regulation_service)]
ReportServiceDep = Annotated[ReportService, Depends(get_report_service)]
JobServiceDep = Annotated[JobService, Depends(get_job_service)]
