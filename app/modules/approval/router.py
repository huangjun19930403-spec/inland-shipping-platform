"""Approval center router."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, require_permission
from app.modules.approval.schemas import (
    ApprovalActionRequest,
    ApprovalAssignRequest,
    ApprovalFlowDefinitionCreateRequest,
    ApprovalFlowDefinitionListQuery,
    ApprovalFlowDefinitionResponse,
    ApprovalFlowDefinitionUpdateRequest,
    ApprovalInstanceDetailResponse,
    ApprovalInstanceListQuery,
    ApprovalInstanceResponse,
    ApprovalInstanceSubmitRequest,
    ApprovalMetadataResponse,
    ApprovalPendingCountResponse,
    ApprovalSubjectDefinitionCreateRequest,
    ApprovalSubjectDefinitionResponse,
    ApprovalSubjectDefinitionUpdateRequest,
    PageResponse,
)
from app.modules.approval.service import ApprovalService

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get(
    "/metadata",
    response_model=ApprovalMetadataResponse,
    dependencies=[Depends(require_permission("APPROVAL:READ"))],
)
async def get_approval_metadata(db: AsyncSession = Depends(get_db)):
    return await ApprovalService(db).get_metadata()


@router.get(
    "/instances",
    response_model=PageResponse[ApprovalInstanceResponse],
    dependencies=[Depends(require_permission("APPROVAL:READ"))],
)
async def list_approval_instances(
    query: ApprovalInstanceListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ApprovalService(db).list_instances(query, current_user.id)


@router.post(
    "/instances",
    response_model=ApprovalInstanceResponse,
    dependencies=[Depends(require_permission("APPROVAL:SUBMIT"))],
)
async def submit_approval_instance(
    body: ApprovalInstanceSubmitRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ApprovalService(db).submit_instance(body, current_user.id)


@router.get(
    "/instances/pending-count",
    response_model=ApprovalPendingCountResponse,
    dependencies=[Depends(require_permission("APPROVAL:READ"))],
)
async def get_pending_count(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ApprovalService(db).get_pending_count(current_user.id)


@router.get(
    "/instances/{instance_id}",
    response_model=ApprovalInstanceDetailResponse,
    dependencies=[Depends(require_permission("APPROVAL:READ"))],
)
async def get_approval_instance_detail(
    instance_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ApprovalService(db).get_instance_detail(instance_id, current_user.id)


@router.post(
    "/instances/{instance_id}/actions/approve",
    response_model=ApprovalInstanceResponse,
    dependencies=[Depends(require_permission("APPROVAL:WRITE"))],
)
async def approve_approval_instance(
    instance_id: int,
    body: ApprovalActionRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ApprovalService(db).approve_instance(instance_id, body, current_user.id)


@router.post(
    "/instances/{instance_id}/actions/reject",
    response_model=ApprovalInstanceResponse,
    dependencies=[Depends(require_permission("APPROVAL:WRITE"))],
)
async def reject_approval_instance(
    instance_id: int,
    body: ApprovalActionRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ApprovalService(db).reject_instance(instance_id, body, current_user.id)


@router.post(
    "/instances/{instance_id}/actions/return",
    response_model=ApprovalInstanceResponse,
    dependencies=[Depends(require_permission("APPROVAL:WRITE"))],
)
async def return_approval_instance(
    instance_id: int,
    body: ApprovalActionRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ApprovalService(db).return_instance(instance_id, body, current_user.id)


@router.post("/instances/{instance_id}/actions/cancel", response_model=ApprovalInstanceResponse)
async def cancel_approval_instance(
    instance_id: int,
    body: ApprovalActionRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ApprovalService(db).cancel_instance(instance_id, body, current_user.id)


@router.post(
    "/instances/{instance_id}/actions/assign",
    response_model=ApprovalInstanceResponse,
    dependencies=[Depends(require_permission("APPROVAL:WRITE"))],
)
async def assign_approval_instance(
    instance_id: int,
    body: ApprovalAssignRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ApprovalService(db).assign_instance(instance_id, body, current_user.id)


@router.get(
    "/flow-definitions",
    response_model=PageResponse[ApprovalFlowDefinitionResponse],
    dependencies=[Depends(require_permission("APPROVAL:CONFIG"))],
)
async def list_flow_definitions(
    query: ApprovalFlowDefinitionListQuery = Depends(),
    db: AsyncSession = Depends(get_db),
):
    return await ApprovalService(db).list_flow_definitions(query)


@router.post(
    "/flow-definitions",
    response_model=ApprovalFlowDefinitionResponse,
    dependencies=[Depends(require_permission("APPROVAL:CONFIG"))],
)
async def create_flow_definition(
    body: ApprovalFlowDefinitionCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    return await ApprovalService(db).create_flow_definition(body)


@router.put(
    "/flow-definitions/{flow_id}",
    response_model=ApprovalFlowDefinitionResponse,
    dependencies=[Depends(require_permission("APPROVAL:CONFIG"))],
)
async def update_flow_definition(
    flow_id: int,
    body: ApprovalFlowDefinitionUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    return await ApprovalService(db).update_flow_definition(flow_id, body)


@router.get(
    "/subject-definitions",
    response_model=list[ApprovalSubjectDefinitionResponse],
    dependencies=[Depends(require_permission("APPROVAL:CONFIG"))],
)
async def list_subject_definitions(db: AsyncSession = Depends(get_db)):
    return await ApprovalService(db).list_subject_definitions()


@router.post(
    "/subject-definitions",
    response_model=ApprovalSubjectDefinitionResponse,
    dependencies=[Depends(require_permission("APPROVAL:CONFIG"))],
)
async def create_subject_definition(
    body: ApprovalSubjectDefinitionCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    return await ApprovalService(db).create_subject_definition(body)


@router.put(
    "/subject-definitions/{definition_id}",
    response_model=ApprovalSubjectDefinitionResponse,
    dependencies=[Depends(require_permission("APPROVAL:CONFIG"))],
)
async def update_subject_definition(
    definition_id: int,
    body: ApprovalSubjectDefinitionUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    return await ApprovalService(db).update_subject_definition(definition_id, body)
