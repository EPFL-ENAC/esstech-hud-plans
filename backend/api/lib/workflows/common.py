import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from prefect import get_client
from prefect.client.schemas.filters import (
    LogFilter,
    LogFilterFlowRunId,
    LogFilterTimestamp,
)
from prefect.client.schemas.objects import TERMINAL_STATES, FlowRun, Log
from prefect.client.schemas.sorting import LogSort
from prefect.events.subscribers import FlowRunSubscriber
from prefect.exceptions import ObjectNotFound
from prefect.types import DateTime
from pydantic import TypeAdapter

BACKEND_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_DATA_DIRECTORY = BACKEND_ROOT / "data" / "workflows"
LOG_PAGE_SIZE = 200
LOG_STREAM_TERMINAL_DRAIN_SECONDS = 3


class WorkflowNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class WorkflowLogsSnapshot:
    flow_run_id: UUID
    captured_at: datetime
    logs: tuple[Log, ...]

    @classmethod
    async def make_snapshot_for_flow_run(cls, flow_run: FlowRun) -> Self:
        captured_at = DateTime.now("UTC")
        logs = await _read_all_log_pages(
            LogFilter(
                flow_run_id=LogFilterFlowRunId(any_=[flow_run.id]),
                timestamp=LogFilterTimestamp(before_=captured_at),
            )
        )
        return cls(
            flow_run_id=flow_run.id,
            captured_at=captured_at,
            logs=logs,
        )


WORKFLOW_LOGS_SNAPSHOT_ADAPTER = TypeAdapter(WorkflowLogsSnapshot)
WORKFLOW_LOG_ADAPTER = TypeAdapter(Log)


@dataclass(frozen=True)
class WorkflowLogStreamItem:
    """A snapshot or incremental log serialized for the workflow event stream."""

    type: Literal["snapshot", "log"]
    data: dict[str, object]

    @classmethod
    def from_snapshot(cls, snapshot: WorkflowLogsSnapshot) -> Self:
        return cls(
            type="snapshot",
            data=WORKFLOW_LOGS_SNAPSHOT_ADAPTER.dump_python(snapshot, mode="json"),
        )

    @classmethod
    def from_log(cls, log: Log) -> Self:
        return cls(
            type="log",
            data=WORKFLOW_LOG_ADAPTER.dump_python(log, mode="json"),
        )

    def to_sse_event(self) -> str:
        serialized_data = json.dumps(self.data)
        return f"event: {self.type}\ndata: {serialized_data}\n\n"


async def get_owned_workflow_run(workflow_id: UUID, owner_id: str) -> FlowRun:
    try:
        async with get_client() as client:
            flow_run = await client.read_flow_run(workflow_id)
    except ObjectNotFound as exc:
        raise WorkflowNotFoundError from exc

    if flow_run.parameters.get("owner_id") != owner_id:
        raise WorkflowNotFoundError

    return flow_run


async def _read_all_log_pages(log_filter: LogFilter) -> tuple[Log, ...]:
    logs: list[Log] = []
    offset = 0

    async with get_client() as client:
        while True:
            page = await client.read_logs(
                log_filter=log_filter,
                limit=LOG_PAGE_SIZE,
                offset=offset,
                sort=LogSort.TIMESTAMP_ASC,
            )
            logs.extend(page)

            if len(page) < LOG_PAGE_SIZE:
                break
            offset += len(page)

    return tuple(logs)


async def stream_workflow_logs(
    flow_run: FlowRun,
) -> AsyncGenerator[WorkflowLogStreamItem, None]:
    seen_log_ids: set[UUID] = set()

    if flow_run.state_type in TERMINAL_STATES:
        snapshot = await WorkflowLogsSnapshot.make_snapshot_for_flow_run(flow_run)
        yield WorkflowLogStreamItem.from_snapshot(snapshot)
        return

    async with FlowRunSubscriber(
        flow_run_id=flow_run.id,
        straggler_timeout=LOG_STREAM_TERMINAL_DRAIN_SECONDS,
    ) as subscription:
        snapshot = await WorkflowLogsSnapshot.make_snapshot_for_flow_run(flow_run)
        seen_log_ids.update(log.id for log in snapshot.logs)
        yield WorkflowLogStreamItem.from_snapshot(snapshot)

        async for item in subscription:
            if isinstance(item, Log) and item.id not in seen_log_ids:
                seen_log_ids.add(item.id)
                yield WorkflowLogStreamItem.from_log(item)

    final_snapshot = await WorkflowLogsSnapshot.make_snapshot_for_flow_run(flow_run)
    for log in final_snapshot.logs:
        if log.id not in seen_log_ids:
            seen_log_ids.add(log.id)
            yield WorkflowLogStreamItem.from_log(log)
