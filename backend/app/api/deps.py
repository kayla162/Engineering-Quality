"""FastAPI 相依注入。router 只透過這裡取得 service，不自己組裝。"""

from typing import Annotated

from fastapi import BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import CurrentUser, require_business_user
from app.jobs.background_runner import BackgroundTasksJobRunner
from app.services.checklist_service import ChecklistService
from app.services.document_service import DocumentService
from app.services.job_service import JobService
from app.services.project_service import ProjectService
from app.services.reference_service import ReferenceService
from app.services.regulation_service import RegulationService
from app.services.report_service import ReportService

DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUserDep = Annotated[CurrentUser, Depends(require_business_user)]


def get_document_service(session: DbSession, user: CurrentUserDep) -> DocumentService:
    return DocumentService(session, user.tenant_id)


def get_reference_service(session: DbSession, user: CurrentUserDep) -> ReferenceService:
    return ReferenceService(session, user.tenant_id)


def get_regulation_service(session: DbSession, user: CurrentUserDep) -> RegulationService:
    return RegulationService(session, user.tenant_id)


def get_report_service(session: DbSession, user: CurrentUserDep) -> ReportService:
    return ReportService(session, user.tenant_id)


def get_project_service(session: DbSession, user: CurrentUserDep) -> ProjectService:
    return ProjectService(session, user.tenant_id)


def get_checklist_service(session: DbSession, user: CurrentUserDep) -> ChecklistService:
    return ChecklistService(session, user.tenant_id)


def get_job_service(
    session: DbSession, background_tasks: BackgroundTasks, user: CurrentUserDep
) -> JobService:
    # 要換成 Celery 時，只需要在這裡換成 CeleryJobRunner()
    return JobService(session, BackgroundTasksJobRunner(background_tasks), user.tenant_id)


DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]
ReferenceServiceDep = Annotated[ReferenceService, Depends(get_reference_service)]
RegulationServiceDep = Annotated[RegulationService, Depends(get_regulation_service)]
ReportServiceDep = Annotated[ReportService, Depends(get_report_service)]
ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
ChecklistServiceDep = Annotated[ChecklistService, Depends(get_checklist_service)]
JobServiceDep = Annotated[JobService, Depends(get_job_service)]
