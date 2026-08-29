from __future__ import annotations

import hmac
from datetime import datetime

from zifisense_agent_api.domain.errors import ApplicationError
from zifisense_agent_api.domain.task_state import TaskState
from zifisense_agent_api.infrastructure.repositories import EvaluationRepository
from zifisense_agent_api.transport.schemas import (
    ApprovalDecisionData,
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    ResponseMeta,
)


class ApprovalService:
    def __init__(self, repository: EvaluationRepository) -> None:
        self._repository = repository

    def decide(
        self,
        *,
        task_id: str,
        request: ApprovalDecisionRequest,
        client_id: str,
        request_id: str,
        trace_id: str,
    ) -> ApprovalDecisionResponse:
        evaluation, task, _ = self._repository.get_task_owner_context(task_id)
        approval = self._repository.get_approval(task_id)
        work_order = self._repository.get_work_order(task_id)
        if evaluation is None or task is None or approval is None or work_order is None:
            raise ApplicationError(404, "RESOURCE_NOT_FOUND", "Pending approval does not exist.")
        if evaluation.client_id != client_id:
            raise ApplicationError(403, "INSUFFICIENT_SCOPE", "Task access is forbidden.")
        if approval.status != "PENDING":
            raise ApplicationError(
                409, "INVALID_STATE_TRANSITION", "This approval was already decided."
            )
        if approval.id != request.approval_id or not hmac.compare_digest(
            approval.approval_challenge, request.approval_challenge
        ):
            raise ApplicationError(
                409, "APPROVAL_CHALLENGE_INVALID", "Approval challenge is invalid."
            )
        if datetime.now().astimezone() >= datetime.fromisoformat(approval.expires_at):
            raise ApplicationError(
                409, "APPROVAL_CHALLENGE_INVALID", "Approval challenge has expired."
            )
        if request.evidence_version != task.evidence_version:
            raise ApplicationError(
                409,
                "EVIDENCE_VERSION_CONFLICT",
                "Evidence changed after this approval was requested.",
                details={"current_evidence_version": task.evidence_version},
            )
        updated_task, updated_work_order, _ = self._repository.apply_approval_decision(
            task_id=task_id,
            decision=request.decision,
            comment=request.comment,
        )
        return ApprovalDecisionResponse(
            request_id=request_id,
            trace_id=trace_id,
            data=ApprovalDecisionData(
                approval_id=approval.id,
                decision=request.decision,
                task_id=task.id,
                task_state=TaskState(updated_task.state),
                work_order_id=updated_work_order.id,
            ),
            meta=ResponseMeta(timestamp=datetime.now().astimezone(), is_degraded=False),
        )
