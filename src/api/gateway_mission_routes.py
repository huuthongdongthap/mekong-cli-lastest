# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Gateway mission create endpoint.

Extracted from gateway.py. Mounted at /v1 prefix by the main app.
Status + SSE stream endpoints are in gateway_mission_stream.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Literal, cast

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.api.gateway_models import CreateMissionRequest, CreateMissionResponse, MissionStatusResponse
from src.core.error_responses import ErrorCode, error_response
from src.core.input_validation import (
    validate_enum_value,
    validate_required,
    validate_string_length,
    validate_url,
)
from src.core.gateway_api import MissionRequest, create_mission
from src.middleware.license_gate import license_gate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["Missions"])

# In-memory mission store (shared with other modules via import)
MISSION_STORE: dict[str, dict] = {}
_MISSION_STORE_MAX = 1000
_MISSION_STORE_LOCK = threading.Lock()
_MISSION_ASYNC_LOCK = asyncio.Lock()


@router.post("/missions", response_model=CreateMissionResponse)
async def create_mission_endpoint(
    request: CreateMissionRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
) -> CreateMissionResponse:
    """Create a new mission from AgencyOS.

    When ``LICENSE_GATE_ENFORCE=1`` the request must carry a valid Bearer JWT
    issued by ``/auth/login``; the gate also checks license status and credits.
    Otherwise the body-provided ``tenant_id`` is used (legacy / dev mode).
    """
    request_id = str(uuid.uuid4())

    import os as _os
    if _os.environ.get("LICENSE_GATE_ENFORCE", "1") != "0":
        gated_tenant = await license_gate(http_request)
        request.tenant_id = gated_tenant

    error = validate_required(request.goal, "goal")
    if error:
        raise HTTPException(status_code=400, detail=error.to_dict())

    error = validate_required(request.tenant_id, "tenant_id")
    if error:
        raise HTTPException(status_code=400, detail=error.to_dict())

    error = validate_string_length(request.goal, "goal", min_len=1, max_len=5000)
    if error:
        raise HTTPException(status_code=400, detail=error.to_dict())

    error = validate_enum_value(
        request.priority, "priority", ["low", "normal", "high"],
        f"Invalid priority '{request.priority}'. Use: low, normal, high",
    )
    if error:
        raise HTTPException(status_code=400, detail=error.to_dict())

    try:
        mission_request = MissionRequest(
            goal=request.goal.strip(),
            tenant_id=request.tenant_id.strip(),
            webhook_url=request.webhook_url.strip() if request.webhook_url else None,
            priority=cast(Literal["low", "normal", "high"], request.priority),
            metadata=request.metadata or {},
        )

        if mission_request.webhook_url:
            error = validate_url(mission_request.webhook_url, "webhook_url")
            if error:
                raise HTTPException(status_code=400, detail=error.to_dict())

        response = create_mission(mission_request)
        mission_id = response.mission_id

        # Evict oldest if over limit
        with _MISSION_STORE_LOCK:
            if len(MISSION_STORE) >= _MISSION_STORE_MAX:
                oldest_key = next(iter(MISSION_STORE))
                del MISSION_STORE[oldest_key]
            MISSION_STORE[mission_id] = {
                    "goal": request.goal,
                    "tenant_id": request.tenant_id,
                    "webhook_url": request.webhook_url,
                    "status": response.status.value,
                    "created_at": response.created_at,
                    "steps": [],
                    "events": [],
                }

        background_tasks.add_task(
            _run_hybrid_router,
            mission_id=mission_id,
            goal=request.goal,
            tenant_id=request.tenant_id,
        )

        logger.info("Mission %s created for tenant %s", mission_id, request.tenant_id)

        return CreateMissionResponse(
            mission_id=mission_id,
            status=response.status.value,
            created_at=response.created_at,
            estimated_steps=response.estimated_steps,
            stream_url=response.stream_url or f"/v1/missions/{mission_id}/stream",
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Mission creation failed: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "INTERNAL_ERROR", "message": "Failed to create mission", "request_id": request_id},
        )


async def _run_hybrid_router(mission_id: str, goal: str, tenant_id: str) -> None:
    """Background task: run hybrid LLM router for a mission."""
    try:
        from src.core.hybrid_router import route_and_execute

        result = await route_and_execute(goal=goal, tenant_id=tenant_id, mission_id=mission_id)

        async with _MISSION_ASYNC_LOCK:
            if mission_id in MISSION_STORE:
                MISSION_STORE[mission_id]["status"] = "completed" if result.success else "failed"
                MISSION_STORE[mission_id]["events"].append({
                    "event_type": "mission.completed" if result.success else "mission.failed",
                    "mission_id": mission_id,
                    "data": {
                        "model_used": result.model_used,
                        "mcu_charged": result.mcu_charged,
                        "output_preview": result.output[:200] if result.output else "",
                    },
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
    except Exception as e:
        logger.error("Hybrid router failed for mission %s: %s", mission_id, e)
        if mission_id in MISSION_STORE:
            MISSION_STORE[mission_id]["status"] = "failed"


@router.get("/missions/{mission_id}", response_model=MissionStatusResponse)
async def get_mission_status(mission_id: str) -> MissionStatusResponse:
    """Get current mission status."""
    if not mission_id or not mission_id.strip():
        raise HTTPException(status_code=400, detail={"error": "INVALID_INPUT", "message": "Mission ID cannot be empty"})

    if mission_id not in MISSION_STORE:
        raise HTTPException(status_code=404, detail="Mission not found")

    mission = MISSION_STORE[mission_id]
    steps = mission.get("steps", [])

    return MissionStatusResponse(
        mission_id=mission_id,
        status=mission["status"],
        goal=mission["goal"],
        tenant_id=mission["tenant_id"],
        created_at=mission["created_at"],
        updated_at=datetime.now(timezone.utc).isoformat(),
        steps_total=len(steps),
        steps_completed=sum(1 for s in steps if s.get("status") == "completed"),
    )


@router.get("/missions/{mission_id}/stream")
async def stream_mission(mission_id: str) -> StreamingResponse:
    """SSE stream for real-time mission progress."""
    if not mission_id or not mission_id.strip():
        raise HTTPException(
            status_code=400,
            detail=error_response(ErrorCode.MISSING_FIELD, "Mission ID is required").to_dict(),
        )

    if mission_id not in MISSION_STORE:
        raise HTTPException(status_code=404, detail="Mission not found")

    async def event_generator() -> AsyncGenerator[str, None]:
        mission = MISSION_STORE[mission_id]
        max_poll_duration = 300
        start_time = asyncio.get_event_loop().time()

        try:
            event = {
                "event_type": "mission.state",
                "mission_id": mission_id,
                "data": {"status": mission["status"], "goal": mission["goal"], "steps": mission.get("steps", [])},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            yield f"data: {json.dumps(event)}\n\n"

            last_event_idx = 0
            while True:
                if (asyncio.get_event_loop().time() - start_time) > max_poll_duration:
                    break

                events = mission.get("events", [])
                if len(events) > last_event_idx:
                    for evt in events[last_event_idx:]:
                        yield f"data: {json.dumps(evt)}\n\n"
                    last_event_idx = len(events)

                if mission["status"] in ["completed", "failed", "cancelled"]:
                    final_event = {
                        "event_type": f"mission.{mission['status']}",
                        "mission_id": mission_id,
                        "data": {"final_state": mission},
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    yield f"data: {json.dumps(final_event)}\n\n"
                    break

                await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            logger.info("Stream cancelled for mission %s", mission_id)
        except Exception as e:
            logger.error("Stream error for mission %s: %s", mission_id, str(e))
            yield f"data: {json.dumps({'event_type': 'mission.error', 'mission_id': mission_id, 'data': {'error': str(e)}})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
