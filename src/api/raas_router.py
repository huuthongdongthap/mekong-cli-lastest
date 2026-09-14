# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""
RaaS API — /v1/ route handlers: tasks, agents, SSE streaming.

Mounts onto the existing gateway FastAPI app via include_router().
All routes require Bearer auth resolved by raas_auth_middleware.require_tenant.
Wires directly to RecipeOrchestrator and AGENT_REGISTRY — no mocks.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

from src.api.raas_auth_middleware import require_tenant
from src.api.raas_task_models import (
    AgentInfo,
    AgentRunRequest,
    AgentRunResponse,
    StepDetail,
    TaskRequest,
    TaskResponse,
    TaskStatus,
    TaskStatusResponse,
)
from src.api.raas_result_models import MissionResultResponse, TaskListResponse, TaskSummary
from src.api.raas_task_store import TaskRecord, get_task_store
from src.core.error_responses import ErrorCode, error_response
from src.core.input_validation import validate_required, validate_string_length
from src.raas.auth import TenantContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["RaaS v1"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_orchestrator() -> Any:
    """Create a RecipeOrchestrator wired to the LLM client."""
    from src.providers.llm.client import get_client
    from src.core.orchestrator import RecipeOrchestrator

    client = get_client()
    return RecipeOrchestrator(
        llm_client=client if client.is_available else None,
        strict_verification=True,
        enable_rollback=True,
    )


def _goal_to_schema(goal: str) -> Optional[str]:
    """Derive a report layout slug from a goal string.

    Maps common goal keywords to schema identifiers used by report pages.
    Returns None when no pattern matches.

    Args:
        goal: High-level goal submitted by the caller.

    Returns:
        Schema slug string or ``None``.
    """
    goal_lower = goal.lower()
    _schema_map = [
        (["marketing", "campaign"], "marketing/campaign"),
        (["sales", "pipeline", "crm"], "sales/pipeline"),
        (["finance", "budget", "revenue"], "finance/budget"),
        (["code", "review", "audit"], "engineering/code-review"),
        (["deploy", "deployment", "release"], "engineering/deployment"),
        (["security", "vulnerability", "cve"], "ops/security"),
        (["okr", "objective", "goal"], "strategy/okr"),
        (["sprint", "backlog", "story"], "product/sprint"),
    ]
    for keywords, schema in _schema_map:
        if any(kw in goal_lower for kw in keywords):
            return schema
    return None


def _result_to_record(record: TaskRecord, result: Any) -> TaskRecord:
    """Populate a TaskRecord from an OrchestrationResult in-place."""
    import datetime as _dt

    from src.core.orchestrator import OrchestrationStatus

    status_map = {
        OrchestrationStatus.SUCCESS: TaskStatus.SUCCESS,
        OrchestrationStatus.FAILED: TaskStatus.FAILED,
        OrchestrationStatus.PARTIAL: TaskStatus.PARTIAL,
        OrchestrationStatus.ROLLED_BACK: TaskStatus.ROLLED_BACK,
    }
    record.status = status_map.get(result.status, TaskStatus.FAILED)
    record.total_steps = result.total_steps
    record.completed_steps = result.completed_steps
    record.failed_steps = result.failed_steps
    record.success_rate = result.success_rate
    record.errors = result.errors
    record.warnings = result.warnings
    record.steps = [
        StepDetail(
            order=sr.step.order,
            title=sr.step.title,
            passed=sr.verification.passed,
            exit_code=sr.execution.exit_code,
            summary=sr.verification.summary,
        )
        for sr in result.step_results
    ]

    # Capture structured output if orchestrator produced it
    if hasattr(result, "structured_output") and result.structured_output:
        record.result_data = result.structured_output
    elif record.status == TaskStatus.SUCCESS and record.steps:
        # Fallback: store step summaries as minimal result_data
        record.result_data = {
            "steps": [
                {"order": s.order, "title": s.title, "summary": s.summary}
                for s in record.steps
            ]
        }

    record.result_schema = _goal_to_schema(record.goal)
    record.completed_at = _dt.datetime.utcnow().isoformat() + "Z"
    return record


# ---------------------------------------------------------------------------
# Task endpoints
# ---------------------------------------------------------------------------


@router.post("/tasks", response_model=TaskResponse, status_code=202)
def submit_task(
    body: TaskRequest,
    tenant: TenantContext = Depends(require_tenant),
) -> TaskResponse:
    """Submit a goal for execution and return a task_id for polling.

    Runs the orchestrator synchronously in the same thread (suitable for
    short goals). For long-running goals, callers should poll GET /v1/tasks/{id}
    or stream via GET /v1/tasks/{id}/stream.

    Args:
        body: Task submission payload.
        tenant: Resolved tenant from Bearer token.

    Returns:
        :class:`TaskResponse` with task_id and initial status.
    """
    # Validate goal
    error = validate_required(body.goal, "goal")
    if error:
        logger.warning("Task submission failed validation: %s", body.goal)
        raise HTTPException(status_code=400, detail=error.to_dict())

    error = validate_string_length(body.goal, "goal", min_len=1, max_len=10000)
    if error:
        raise HTTPException(status_code=400, detail=error.to_dict())

    store = get_task_store()

    try:
        record = store.create(goal=body.goal, tenant_id=tenant.tenant_id)
        record.status = TaskStatus.RUNNING
        store.update(record)

        orchestrator = _build_orchestrator()
        result = orchestrator.run_from_goal(body.goal)
        record = _result_to_record(record, result)

    except ValueError as e:
        # Business logic errors
        logger.warning("Task submission business error: %s", e)
        record = store.create(goal=body.goal, tenant_id=tenant.tenant_id)
        record.status = TaskStatus.FAILED
        record.errors.append(f"validation_error: {e}")

    except Exception as exc:
        logger.error("Task execution failed: %s", str(exc), exc_info=True)
        record = store.create(goal=body.goal, tenant_id=tenant.tenant_id)
        record.status = TaskStatus.FAILED
        record.errors.append(f"execution_failed: {str(exc)}")

    store.update(record)
    return TaskResponse(
        task_id=record.task_id,
        status=record.status,
        tenant_id=tenant.tenant_id,
    )


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
def get_task_status(
    task_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> TaskStatusResponse:
    """Poll full status and result for a previously submitted task.

    Args:
        task_id: Identifier returned by POST /v1/tasks.
        tenant: Resolved tenant (enforces tenant isolation).

    Returns:
        :class:`TaskStatusResponse` with current status and step details.

    Raises:
        HTTPException 400: Invalid task_id format.
        HTTPException 404: Task not found or belongs to another tenant.
    """
    # Validate task_id format
    if not task_id or not task_id.strip():
        raise HTTPException(
            status_code=400,
            detail=error_response(
                ErrorCode.INVALID_INPUT,
                "Task ID is required and cannot be empty",
            ).to_dict(),
        )

    try:
        store = get_task_store()
        record = store.get(task_id=task_id, tenant_id=tenant.tenant_id)
        if record is None:
            logger.warning("Task not found: %s", task_id)
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

        return TaskStatusResponse(
            task_id=record.task_id,
            status=record.status,
            goal=record.goal,
            tenant_id=record.tenant_id,
            total_steps=record.total_steps,
            completed_steps=record.completed_steps,
            failed_steps=record.failed_steps,
            success_rate=record.success_rate,
            errors=record.errors,
            warnings=record.warnings,
            steps=record.steps,
            result_data=record.result_data,
            result_schema=record.result_schema,
            completed_at=record.completed_at,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Get task status failed for %s: %s", task_id, str(exc))
        raise HTTPException(
            status_code=500,
            detail={
                "error": "INTERNAL_ERROR",
                "message": "Failed to get task status",
            },
        )


@router.get("/tasks/{task_id}/stream")
async def stream_task(
    task_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> StreamingResponse:
    """Stream task execution progress as Server-Sent Events (SSE).

    Runs the orchestrator in a background thread and yields step events
    as they complete. Clients connect with ``Accept: text/event-stream``.

    Args:
        task_id: Identifier returned by POST /v1/tasks.
        tenant: Resolved tenant.

    Returns:
        :class:`StreamingResponse` with SSE content-type.

    Raises:
        HTTPException 400: Invalid task_id format.
        HTTPException 404: Task not found or belongs to another tenant.
    """
    # Validate task_id format
    if not task_id or not task_id.strip():
        raise HTTPException(
            status_code=400,
            detail=error_response(
                ErrorCode.INVALID_INPUT,
                "Task ID is required and cannot be empty",
            ).to_dict(),
        )

    store = get_task_store()
    record = store.get(task_id=task_id, tenant_id=tenant.tenant_id)
    if record is None:
        logger.warning("Task not found: %s", task_id)
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

    async def _event_stream() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue[Dict] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _on_step(step_result: Any, current: Any) -> None:
            event = {
                "type": "step",
                "order": step_result.step.order,
                "title": step_result.step.title,
                "passed": step_result.verification.passed,
                "exit_code": step_result.execution.exit_code,
                "summary": step_result.verification.summary,
                "completed": current.completed_steps,
                "total": current.total_steps,
            }
            asyncio.run_coroutine_threadsafe(queue.put(event), loop)

        def _run() -> Any:
            orch = _build_orchestrator()
            return orch.run_from_goal(record.goal, progress_callback=_on_step)

        future = loop.run_in_executor(None, _run)

        # Drain step events until execution finishes
        while not future.done():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.5)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                continue

        # Flush remaining queued events
        while not queue.empty():
            event = queue.get_nowait()
            yield f"data: {json.dumps(event)}\n\n"

        # Emit final completion event
        try:
            result = future.result()
            record_updated = _result_to_record(record, result)
            store.update(record_updated)
            done_event = {
                "type": "complete",
                "status": record_updated.status.value,
                "success_rate": record_updated.success_rate,
                "errors": record_updated.errors,
            }
        except Exception as exc:
            logger.error("Stream finalization error for %s: %s", task_id, str(exc))
            done_event = {"type": "error", "message": str(exc)}

        yield f"data: {json.dumps(done_event)}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Result + list endpoints
# ---------------------------------------------------------------------------


@router.get("/tasks", response_model=TaskListResponse)
def list_tasks(
    tenant: TenantContext = Depends(require_tenant),
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    status: Optional[str] = Query(None, description="Filter by TaskStatus value"),
) -> TaskListResponse:
    """List tasks for the authenticated tenant with pagination and optional status filter.

    Args:
        tenant: Resolved tenant.
        limit: Max records to return (1-100, default 20).
        offset: Records to skip for pagination.
        status: Optional status string to filter (pending/running/success/failed/partial).

    Returns:
        :class:`TaskListResponse` with paginated task summaries.
    """
    store = get_task_store()
    records = store.list_tasks(
        tenant_id=tenant.tenant_id,
        limit=limit,
        offset=offset,
        status=status,
    )
    summaries = [
        TaskSummary(
            task_id=r.task_id,
            goal=r.goal,
            status=r.status,
            result_schema=r.result_schema,
            completed_at=r.completed_at,
            success_rate=r.success_rate,
        )
        for r in records
    ]
    # Total count (all matching records, before pagination)
    all_records = store.list_tasks(
        tenant_id=tenant.tenant_id,
        limit=10000,
        offset=0,
        status=status,
    )
    return TaskListResponse(
        tasks=summaries,
        total=len(all_records),
        limit=limit,
        offset=offset,
    )


@router.get("/tasks/{task_id}/result", response_model=MissionResultResponse)
def get_task_result(
    task_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> Any:
    """Return only the structured result payload for a completed task.

    Lighter than GET /v1/tasks/{id} — omits execution metadata (steps, errors).
    Designed to be cached by report pages.

    Args:
        task_id: Task identifier.
        tenant: Resolved tenant.

    Returns:
        :class:`MissionResultResponse` with result_data and result_schema.

    Raises:
        HTTPException 404: Task not found, belongs to another tenant, or still running.
        HTTPException 204: Task complete but no result_data stored (via JSONResponse).
    """
    if not task_id or not task_id.strip():
        raise HTTPException(status_code=400, detail="task_id is required")

    store = get_task_store()
    record = store.get(task_id=task_id, tenant_id=tenant.tenant_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

    if record.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
        raise HTTPException(status_code=404, detail="Task not yet complete.")

    if not record.result_data:
        # 204 No Content — task done but no structured result
        return JSONResponse(status_code=204, content=None)

    return MissionResultResponse(
        task_id=record.task_id,
        goal=record.goal,
        result_schema=record.result_schema,
        result_data=record.result_data,
        completed_at=record.completed_at,
    )


@router.patch("/tasks/{task_id}/result", response_model=MissionResultResponse)
def save_task_result(
    task_id: str,
    body: Dict[str, Any],
    tenant: TenantContext = Depends(require_tenant),
) -> MissionResultResponse:
    """Store structured result data on an existing task (called by orchestrator).

    Allows external orchestrators to push result_data after execution completes.
    Validates payload size (1 MB limit).

    Args:
        task_id: Task identifier.
        body: Free-form JSON dict — the structured command output.
        tenant: Resolved tenant.

    Returns:
        Updated :class:`MissionResultResponse`.

    Raises:
        HTTPException 404: Task not found.
        HTTPException 413: Payload exceeds 1 MB.
    """
    if not task_id or not task_id.strip():
        raise HTTPException(status_code=400, detail="task_id is required")

    store = get_task_store()
    try:
        schema = body.pop("_result_schema", None)
        record = store.save_result(
            task_id=task_id,
            tenant_id=tenant.tenant_id,
            data=body,
            schema=schema,
        )
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    if record is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

    return MissionResultResponse(
        task_id=record.task_id,
        goal=record.goal,
        result_schema=record.result_schema,
        result_data=record.result_data or {},
        completed_at=record.completed_at,
    )


# ---------------------------------------------------------------------------
# Agent endpoints
# ---------------------------------------------------------------------------


@router.get("/agents", response_model=List[AgentInfo])
def list_agents(
    tenant: TenantContext = Depends(require_tenant),
) -> List[AgentInfo]:
    """List all agents registered in AGENT_REGISTRY.

    Args:
        tenant: Resolved tenant (auth required, tenant unused in response).

    Returns:
        List of :class:`AgentInfo` with name and description.
    """
    from src.agents import registry

    agents: List[AgentInfo] = []
    for name in registry.list_agents():
        cls = registry.get(name)
        description = (cls.__doc__ or "").strip().splitlines()[0] if cls.__doc__ else name
        agents.append(AgentInfo(name=name, description=description))
    return agents


@router.post("/agents/{name}/run", response_model=AgentRunResponse)
def run_agent(
    name: str,
    body: AgentRunRequest,
    tenant: TenantContext = Depends(require_tenant),
) -> AgentRunResponse:
    """Run a named agent directly with a goal.

    Instantiates the agent from AGENT_REGISTRY, calls plan() then execute(),
    and returns structured output. Does NOT go through the full orchestrator.

    Args:
        name: Registered agent name (e.g. 'git', 'file', 'shell').
        body: Goal and options for the agent.
        tenant: Resolved tenant.

    Returns:
        :class:`AgentRunResponse` with agent output.

    Raises:
        HTTPException 404: Agent name not registered.
        HTTPException 500: Agent execution error.
    """
    # Validate agent name
    if not name or not name.strip():
        raise HTTPException(
            status_code=400,
            detail=error_response(
                ErrorCode.INVALID_INPUT,
                "Agent name is required",
            ).to_dict(),
        )

    # Validate goal
    error = validate_required(body.goal, "goal")
    if error:
        raise HTTPException(status_code=400, detail=error.to_dict())

    from src.agents import registry

    if name not in registry:
        available = registry.list_agents()
        logger.warning("Agent not found: %s. Available: %s", name, available)
        raise HTTPException(
            status_code=404,
            detail={
                "error": "NOT_FOUND",
                "message": f"Agent '{name}' not found",
                "available_agents": available,
            },
        )

    try:
        agent_cls = registry.get(name)
        agent = agent_cls()

        plan = agent.plan(body.goal)
        exec_result = agent.execute(plan)

        output = str(exec_result) if exec_result is not None else ""
        return AgentRunResponse(agent=name, status="success", output=output)

    except TimeoutError as e:
        logger.error("Agent %s timed out: %s", name, str(e))
        raise HTTPException(
            status_code=504,  # Gateway Timeout
            detail={
                "error": "TIMEOUT",
                "message": f"Agent '{name}' timed out",
            },
        )

    except Exception as exc:
        logger.error("Agent %s execution error: %s", name, str(exc), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "AGENT_EXECUTION_ERROR",
                "message": f"Agent '{name}' failed: {str(exc)}",
            },
        ) from exc


__all__ = ["router"]
