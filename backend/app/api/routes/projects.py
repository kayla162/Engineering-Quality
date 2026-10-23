"""專案、專案文件角色與工項清單的 API。

工項清單是「工項檢核表」的第一欄，來源是標單的詳細價目表
（docs/superpowers/specs/2026-09-11-工項檢核表-design.md 第 5 節）。
"""

import uuid

from fastapi import APIRouter, Request, status

from app.api.deps import AuditServiceDep, CurrentUserDep, ProjectServiceDep
from app.core.enums import AuditAction
from app.services.project_service import ProjectService
from app.schemas.project import (
    AttachDocumentRequest,
    ProjectCreate,
    ProjectDocumentOut,
    ProjectListOut,
    ProjectOut,
    WorkItemListOut,
    WorkItemOut,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    request: Request,
    service: ProjectServiceDep,
    audit: AuditServiceDep,
    user: CurrentUserDep,
):
    # 名稱已經由 ProjectCreate 的 validator 去過空白
    project = await service.create_project(payload.name)
    await audit.record(
        AuditAction.PROJECT_CREATED,
        actor=user,
        resource_type="project",
        resource_id=project.id,
        detail={"name": project.name},
        request=request,
        commit=True,
    )
    return ProjectOut.from_model(project)


@router.get("", response_model=ProjectListOut)
async def list_projects(service: ProjectServiceDep):
    projects = await service.list_projects()
    return ProjectListOut(
        total=len(projects), items=[ProjectOut.from_model(p) for p in projects]
    )


@router.post(
    "/{project_id}/documents",
    response_model=ProjectDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def attach_document(
    project_id: uuid.UUID,
    payload: AttachDocumentRequest,
    request: Request,
    service: ProjectServiceDep,
    audit: AuditServiceDep,
    user: CurrentUserDep,
):
    link = await service.attach_document(project_id, payload.document_id, payload.role)
    await audit.record(
        AuditAction.PROJECT_DOCUMENT_ATTACHED,
        actor=user,
        resource_type="project",
        resource_id=project_id,
        detail={"document_id": str(payload.document_id), "role": payload.role},
        request=request,
        commit=True,
    )
    return ProjectDocumentOut.from_model(link)


@router.post(
    "/{project_id}/work-items",
    response_model=WorkItemListOut,
    status_code=status.HTTP_201_CREATED,
)
async def build_work_items(
    project_id: uuid.UUID,
    request: Request,
    service: ProjectServiceDep,
    audit: AuditServiceDep,
    user: CurrentUserDep,
):
    """從專案的標單重建工項清單。重跑會取代舊的，不會累加。"""
    await service.build_work_items(project_id)
    result = await _work_item_list(project_id, service)
    await audit.record(
        AuditAction.WORK_ITEMS_BUILT,
        actor=user,
        resource_type="project",
        resource_id=project_id,
        detail={"total": result.total, "with_spec_chapter": result.with_spec_chapter},
        request=request,
        commit=True,
    )
    return result


@router.get("/{project_id}/work-items", response_model=WorkItemListOut)
async def list_work_items(project_id: uuid.UUID, service: ProjectServiceDep):
    return await _work_item_list(project_id, service)


async def _work_item_list(project_id: uuid.UUID, service: ProjectService) -> WorkItemListOut:
    items = await service.work_items(project_id)
    rows = [
        WorkItemOut.from_model(item, await service.spec_chapter_for(item.cost_code))
        for item in items
    ]
    return WorkItemListOut(
        total=len(rows),
        with_spec_chapter=sum(1 for r in rows if r.spec_chapter is not None),
        items=rows,
    )
