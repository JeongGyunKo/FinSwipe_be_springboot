from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone

from app.schemas.storage import (
    AnalysisOutcome,
    AnalysisStatus,
    PipelineStageName,
    PipelineStageResult,
    PipelineStageStatus,
    StoragePayloadError,
)


_FAILURE_STATUS_BY_STAGE = {
    PipelineStageName.FETCH: AnalysisStatus.FETCH_FAILED,
    PipelineStageName.CLEAN: AnalysisStatus.CLEAN_FAILED,
    PipelineStageName.VALIDATE: AnalysisStatus.VALIDATE_FAILED,
    PipelineStageName.SUMMARIZE: AnalysisStatus.SUMMARIZE_FAILED,
    PipelineStageName.SENTIMENT: AnalysisStatus.SENTIMENT_FAILED,
    PipelineStageName.XAI: AnalysisStatus.XAI_FAILED,
    PipelineStageName.MIXED_DETECTION: AnalysisStatus.MIXED_DETECTION_FAILED,
    PipelineStageName.BUILD_PAYLOAD: AnalysisStatus.BUILD_PAYLOAD_FAILED,
    PipelineStageName.PERSIST: AnalysisStatus.PERSIST_FAILED,
}

_FILTERED_STATUS_BY_STAGE = {
    PipelineStageName.CLEAN: AnalysisStatus.CLEAN_FILTERED,
    PipelineStageName.VALIDATE: AnalysisStatus.VALIDATE_FILTERED,
}

_STAGE_ORDER = [
    PipelineStageName.FETCH,
    PipelineStageName.CLEAN,
    PipelineStageName.VALIDATE,
    PipelineStageName.SUMMARIZE,
    PipelineStageName.SENTIMENT,
    PipelineStageName.XAI,
    PipelineStageName.MIXED_DETECTION,
    PipelineStageName.BUILD_PAYLOAD,
    PipelineStageName.PERSIST,
]


@dataclass(slots=True)
class _MutableStageRecord:
    stage: PipelineStageName
    status: PipelineStageStatus = PipelineStageStatus.PENDING
    fatal: bool = False
    message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class PipelineStatusTracker:
    """Centralized stage status and error propagation for the enrichment pipeline."""

    def __init__(self) -> None:
        self._stages = OrderedDict(
            (stage, _MutableStageRecord(stage=stage))
            for stage in _STAGE_ORDER
        )
        self._errors: list[StoragePayloadError] = []

    def start(self, stage: PipelineStageName) -> None:
        record = self._stages[stage]
        record.started_at = _utcnow()
        record.status = PipelineStageStatus.PENDING
        record.message = None
        record.fatal = False
        record.completed_at = None

    def complete(self, stage: PipelineStageName, message: str | None = None) -> None:
        record = self._stages[stage]
        if record.started_at is None:
            record.started_at = _utcnow()
        record.status = PipelineStageStatus.COMPLETED
        record.message = message
        record.completed_at = _utcnow()
        record.fatal = False

    def fail(self, stage: PipelineStageName, message: str, *, fatal: bool) -> None:
        record = self._stages[stage]
        if record.started_at is None:
            record.started_at = _utcnow()
        record.status = PipelineStageStatus.FAILED
        record.message = message
        record.completed_at = _utcnow()
        record.fatal = fatal
        self._errors.append(
            StoragePayloadError(
                stage=stage,
                message=message,
                fatal=fatal,
            )
        )

    def skip(self, stage: PipelineStageName, message: str) -> None:
        record = self._stages[stage]
        if record.started_at is None:
            record.started_at = _utcnow()
        record.status = PipelineStageStatus.SKIPPED
        record.message = message
        record.completed_at = _utcnow()
        record.fatal = False

    def filter(self, stage: PipelineStageName, message: str) -> None:
        record = self._stages[stage]
        if record.started_at is None:
            record.started_at = _utcnow()
        record.status = PipelineStageStatus.FILTERED
        record.message = message
        record.completed_at = _utcnow()
        record.fatal = False

    def snapshot_stage_statuses(self) -> list[PipelineStageResult]:
        return [
            PipelineStageResult(
                stage=record.stage,
                status=record.status,
                fatal=record.fatal,
                message=record.message,
                started_at=record.started_at,
                completed_at=record.completed_at,
            )
            for record in self._stages.values()
        ]

    def errors(self) -> list[StoragePayloadError]:
        return list(self._errors)

    def derive_status(self) -> tuple[AnalysisStatus, AnalysisOutcome]:
        fatal_failures = [
            record
            for record in self._stages.values()
            if record.status == PipelineStageStatus.FAILED and record.fatal
        ]
        if fatal_failures:
            failed_stage = fatal_failures[0].stage
            return _FAILURE_STATUS_BY_STAGE[failed_stage], AnalysisOutcome.FATAL_FAILURE

        filtered_stages = [
            record
            for record in self._stages.values()
            if record.status == PipelineStageStatus.FILTERED
        ]
        if filtered_stages:
            filtered_stage = filtered_stages[0].stage
            return _FILTERED_STATUS_BY_STAGE[filtered_stage], AnalysisOutcome.FILTERED

        nonfatal_failures = [
            record
            for record in self._stages.values()
            if record.status == PipelineStageStatus.FAILED and not record.fatal
        ]
        if nonfatal_failures:
            if len(nonfatal_failures) == 1:
                failed_stage = nonfatal_failures[0].stage
                if failed_stage == PipelineStageName.SUMMARIZE:
                    return (
                        AnalysisStatus.COMPLETED_WITH_PARTIAL_RESULTS,
                        AnalysisOutcome.PARTIAL_SUCCESS,
                    )
                return _FAILURE_STATUS_BY_STAGE[failed_stage], AnalysisOutcome.PARTIAL_SUCCESS
            return (
                AnalysisStatus.COMPLETED_WITH_PARTIAL_RESULTS,
                AnalysisOutcome.PARTIAL_SUCCESS,
            )

        if all(
            self._stages[stage].status in {
                PipelineStageStatus.COMPLETED,
                PipelineStageStatus.SKIPPED,
            }
            for stage in _STAGE_ORDER
        ):
            return AnalysisStatus.COMPLETED, AnalysisOutcome.SUCCESS

        return AnalysisStatus.PENDING, AnalysisOutcome.PARTIAL_SUCCESS


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)