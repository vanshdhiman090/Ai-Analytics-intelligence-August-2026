"""Typed, bounded contracts for manager-to-specialist delegation.

The workflow state is deliberately *not* part of these contracts.  A manager
must select the minimum named inputs a specialist needs and the specialist must
return only its declared outputs.  This keeps delegation reviewable, makes
retries idempotent, and prevents specialists from silently mutating shared
state.
"""

from __future__ import annotations

import hashlib
import re
from enum import Enum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret|authorization|cookie)"
    r"\s*[:=]\s*([^\s,;]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/@\s:]+:[^/@\s]+@", re.IGNORECASE)
_WINDOWS_USER_PATH = re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+\\")
_WHITESPACE = re.compile(r"\s+")
_SENSITIVE_FIELD_NAME = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret|authorization|cookie)"
)


def sanitize_diagnostic(value: object, *, limit: int = 500) -> str:
    """Return a single-line, bounded diagnostic with common secrets removed.

    This function intentionally accepts only an exception/message, not a
    traceback or workflow payload.  It is suitable for audit logs and user-safe
    manager feedback, but it is not a replacement for access control.
    """

    text = _WHITESPACE.sub(" ", str(value)).strip()
    text = _BEARER_TOKEN.sub("Bearer [REDACTED]", text)
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    text = _URL_CREDENTIALS.sub(lambda match: f"{match.group('scheme')}[REDACTED]@", text)
    text = _WINDOWS_USER_PATH.sub(lambda _match: "[USER_PATH]\\", text)
    return text[:limit]


def _clean_identifier(value: str) -> str:
    return value.strip()


class FrozenContractModel(BaseModel):
    """Strict immutable base used by every delegation contract."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class WorkflowMode(str, Enum):
    FAST = "fast"
    PROFESSIONAL = "professional"


class SpecialistResultStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class ReviewStatus(str, Enum):
    APPROVED = "approved"
    REVISION_REQUIRED = "revision_required"
    BLOCKED = "blocked"


class ErrorKind(str, Enum):
    INPUT_INVALID = "input_invalid"
    CONTRACT_VIOLATION = "contract_violation"
    TRANSIENT_DEPENDENCY = "transient_dependency"
    PERMISSION_REQUIRED = "permission_required"
    POLICY_BLOCK = "policy_block"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class RetryDisposition(str, Enum):
    NEVER = "never"
    IMMEDIATE = "immediate"
    BACKOFF = "backoff"
    AFTER_INPUT = "after_input"


class TaskContext(FrozenContractModel):
    """Trace context required to supervise a bounded specialist invocation."""

    session_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    manager_name: str = Field(min_length=1, max_length=100)
    specialist_name: str = Field(min_length=1, max_length=100)
    stage: str = Field(min_length=1, max_length=64)
    workflow_mode: WorkflowMode = WorkflowMode.PROFESSIONAL
    parent_task_id: str | None = Field(default=None, min_length=1, max_length=128)

    _strip_identifiers = field_validator(
        "session_id", "trace_id", "manager_name", "specialist_name", "stage", "parent_task_id"
    )(lambda value: _clean_identifier(value) if value is not None else value)


class IdempotencyMetadata(FrozenContractModel):
    """Metadata a manager uses to make retries intentional and auditable."""

    key: str = Field(min_length=3, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    scope: str = Field(default="specialist_task", min_length=1, max_length=80)
    attempt: int = Field(default=1, ge=1)
    max_attempts: int = Field(default=1, ge=1, le=10)
    input_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    side_effect_free: bool = True

    @model_validator(mode="after")
    def validate_attempt_window(self) -> "IdempotencyMetadata":
        if self.attempt > self.max_attempts:
            raise ValueError("attempt cannot exceed max_attempts")
        return self


class ContractValue(FrozenContractModel):
    """One explicitly selected input or output.

    ``value`` is intentionally opaque so existing domain Pydantic models can be
    carried without this module depending on them.  The contract object itself
    is immutable; callers should pass immutable values or references for large
    objects rather than mutable workflow state.
    """

    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    value: Any
    schema_name: str | None = Field(default=None, max_length=120)
    source_ref: str | None = Field(default=None, max_length=500)


class Diagnostic(FrozenContractModel):
    """Sanitized diagnostic safe for manager review and audit storage."""

    code: str = Field(min_length=2, max_length=80, pattern=r"^[A-Z][A-Z0-9_]+$")
    message: str = Field(min_length=1, max_length=500)
    severity: str = Field(default="error", pattern=r"^(info|warning|error)$")

    @field_validator("message", mode="before")
    @classmethod
    def sanitize_message(cls, value: object) -> str:
        return sanitize_diagnostic(value)

    @classmethod
    def from_exception(cls, error: Exception, *, code: str = "SPECIALIST_ERROR") -> "Diagnostic":
        return cls(code=code, message=f"{type(error).__name__}: {error}")


class ErrorClassification(FrozenContractModel):
    """Manager-readable failure category and retry policy."""

    kind: ErrorKind
    retry: RetryDisposition
    code: str = Field(min_length=2, max_length=80, pattern=r"^[A-Z][A-Z0-9_]+$")
    summary: str = Field(min_length=1, max_length=500)
    suggested_action: str | None = Field(default=None, max_length=500)

    @field_validator("summary", "suggested_action", mode="before")
    @classmethod
    def sanitize_text(cls, value: object) -> str | None:
        return None if value is None else sanitize_diagnostic(value)

    @model_validator(mode="after")
    def validate_retry_policy(self) -> "ErrorClassification":
        if self.kind in {ErrorKind.CONTRACT_VIOLATION, ErrorKind.POLICY_BLOCK} and self.retry != RetryDisposition.NEVER:
            raise ValueError(f"{self.kind.value} errors must not be retried")
        if self.kind in {ErrorKind.INPUT_INVALID, ErrorKind.PERMISSION_REQUIRED} and self.retry != RetryDisposition.AFTER_INPUT:
            raise ValueError(f"{self.kind.value} errors require user or operator input")
        if self.kind in {ErrorKind.TRANSIENT_DEPENDENCY, ErrorKind.RESOURCE_EXHAUSTED} and self.retry != RetryDisposition.BACKOFF:
            raise ValueError(f"{self.kind.value} errors require a backoff retry")
        return self


class SpecialistTask(FrozenContractModel):
    """A manager assignment containing only selected, named inputs."""

    contract_version: str = Field(default="1.0", pattern=r"^1\.0(?:\.0)?$")
    task_id: str = Field(min_length=1, max_length=128)
    task_type: str = Field(min_length=1, max_length=100)
    objective: str = Field(min_length=10, max_length=2000)
    context: TaskContext
    idempotency: IdempotencyMetadata
    required_inputs: tuple[str, ...] = Field(default_factory=tuple)
    required_outputs: tuple[str, ...] = Field(min_length=1)
    inputs: tuple[ContractValue, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_contract(self) -> "SpecialistTask":
        input_names = _unique_names(self.inputs, "input")
        required_inputs = _unique_strings(self.required_inputs, "required input")
        _unique_strings(self.required_outputs, "required output")
        missing = sorted(set(required_inputs) - input_names)
        if missing:
            raise ValueError(f"Missing required specialist inputs: {missing}")
        reserved = {"state", "full_state", "workflow_state"} & input_names
        if reserved:
            raise ValueError("Full mutable workflow state cannot be delegated; select bounded named inputs")
        if self.context.specialist_name == self.context.manager_name:
            raise ValueError("manager and specialist must have distinct identities")
        return self

    def input_value(self, name: str) -> Any:
        for item in self.inputs:
            if item.name == name:
                return item.value
        raise KeyError(name)


class SpecialistResult(FrozenContractModel):
    """A specialist response; it does not mutate or return the workflow state."""

    contract_version: str = Field(default="1.0", pattern=r"^1\.0(?:\.0)?$")
    result_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=128)
    specialist_name: str = Field(min_length=1, max_length=100)
    status: SpecialistResultStatus
    outputs: tuple[ContractValue, ...] = Field(default_factory=tuple)
    diagnostics: tuple[Diagnostic, ...] = Field(default_factory=tuple)
    error: ErrorClassification | None = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> "SpecialistResult":
        _unique_names(self.outputs, "output")
        if self.status == SpecialistResultStatus.COMPLETED and self.error is not None:
            raise ValueError("A completed specialist result cannot include an error classification")
        if self.status in {SpecialistResultStatus.FAILED, SpecialistResultStatus.BLOCKED} and self.error is None:
            raise ValueError("Failed or blocked specialist results require an error classification")
        return self

    def output_value(self, name: str) -> Any:
        for item in self.outputs:
            if item.name == name:
                return item.value
        raise KeyError(name)


class ReviewDecision(FrozenContractModel):
    """Independent manager/quality-manager decision on a specialist result."""

    contract_version: str = Field(default="1.0", pattern=r"^1\.0(?:\.0)?$")
    review_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=128)
    result_id: str = Field(min_length=1, max_length=128)
    reviewer_name: str = Field(min_length=1, max_length=100)
    status: ReviewStatus
    reasons: tuple[str, ...] = Field(default_factory=tuple)
    requested_changes: tuple[str, ...] = Field(default_factory=tuple)
    diagnostics: tuple[Diagnostic, ...] = Field(default_factory=tuple)

    @field_validator("reasons", "requested_changes", mode="before")
    @classmethod
    def sanitize_review_text(cls, values: object) -> object:
        if isinstance(values, (list, tuple)):
            return tuple(sanitize_diagnostic(value) for value in values)
        return values

    @model_validator(mode="after")
    def validate_decision(self) -> "ReviewDecision":
        if self.status == ReviewStatus.APPROVED and self.requested_changes:
            raise ValueError("Approved results cannot request changes")
        if self.status == ReviewStatus.REVISION_REQUIRED and not self.requested_changes:
            raise ValueError("revision_required decisions must specify requested_changes")
        if self.status == ReviewStatus.BLOCKED and not self.reasons:
            raise ValueError("blocked decisions must state at least one reason")
        return self


def _unique_strings(values: tuple[str, ...], label: str) -> set[str]:
    cleaned = [value.strip() for value in values]
    if any(not value for value in cleaned):
        raise ValueError(f"{label} names cannot be blank")
    if len(set(cleaned)) != len(cleaned):
        raise ValueError(f"Duplicate {label} names are not allowed")
    return set(cleaned)


def _unique_names(values: tuple[ContractValue, ...], label: str) -> set[str]:
    names = [item.name for item in values]
    if len(set(names)) != len(names):
        raise ValueError(f"Duplicate {label} names are not allowed")
    return set(names)


def validate_specialist_result(task: SpecialistTask, result: SpecialistResult) -> SpecialistResult:
    """Validate identity and required-output coverage before manager review."""

    if result.task_id != task.task_id:
        raise ValueError("Specialist result task_id does not match its assignment")
    if result.specialist_name != task.context.specialist_name:
        raise ValueError("Specialist result identity does not match its assignment")
    if result.status == SpecialistResultStatus.COMPLETED:
        output_names = {item.name for item in result.outputs}
        missing = sorted(set(task.required_outputs) - output_names)
        if missing:
            raise ValueError(f"Specialist result is missing required outputs: {missing}")
    return result


def classify_error(error: Exception) -> ErrorClassification:
    """Classify common failures into deterministic manager retry policies."""

    summary = f"{type(error).__name__}: {error}"
    if isinstance(error, ValidationError):
        return ErrorClassification(
            kind=ErrorKind.CONTRACT_VIOLATION,
            retry=RetryDisposition.NEVER,
            code="CONTRACT_VALIDATION_FAILED",
            summary=summary,
            suggested_action="Correct the task or result contract before running the specialist again.",
        )
    if isinstance(error, PermissionError):
        return ErrorClassification(
            kind=ErrorKind.PERMISSION_REQUIRED,
            retry=RetryDisposition.AFTER_INPUT,
            code="PERMISSION_REQUIRED",
            summary=summary,
            suggested_action="Request the missing permission from an authorized operator.",
        )
    if isinstance(error, (TimeoutError, ConnectionError)):
        return ErrorClassification(
            kind=ErrorKind.TRANSIENT_DEPENDENCY,
            retry=RetryDisposition.BACKOFF,
            code="DEPENDENCY_TEMPORARILY_UNAVAILABLE",
            summary=summary,
            suggested_action="Retry with bounded exponential backoff using the same idempotency key.",
        )
    if isinstance(error, (MemoryError, OSError)):
        return ErrorClassification(
            kind=ErrorKind.RESOURCE_EXHAUSTED,
            retry=RetryDisposition.BACKOFF,
            code="RESOURCE_UNAVAILABLE",
            summary=summary,
            suggested_action="Reduce the bounded workload or retry after resources recover.",
        )
    if isinstance(error, (ValueError, TypeError, KeyError)):
        return ErrorClassification(
            kind=ErrorKind.INPUT_INVALID,
            retry=RetryDisposition.AFTER_INPUT,
            code="SPECIALIST_INPUT_INVALID",
            summary=summary,
            suggested_action="Correct or supply the required bounded input before retrying.",
        )
    return ErrorClassification(
        kind=ErrorKind.UNKNOWN,
        retry=RetryDisposition.NEVER,
        code="UNCLASSIFIED_FAILURE",
        summary=summary,
        suggested_action="Escalate for review; do not retry automatically without a known recovery policy.",
    )


def build_idempotency_key(
    *, session_id: str, specialist_name: str, task_type: str, input_fingerprint: str
) -> str:
    """Create a stable, non-secret idempotency key from contract metadata."""

    material = "|".join((session_id, specialist_name, task_type, input_fingerprint))
    return f"specialist:{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


def fingerprint_inputs(inputs: Mapping[str, object]) -> str:
    """Create a stable fingerprint for simple input references/identifiers.

    Managers should fingerprint source references and checksums, not raw dataset
    contents or credentials.  Values are sanitized before hashing so obvious
    secrets are never incorporated into the digest material.
    """

    material = "|".join(
        f"{key}={'[REDACTED]' if _SENSITIVE_FIELD_NAME.fullmatch(key) else sanitize_diagnostic(inputs[key], limit=200)}"
        for key in sorted(inputs)
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


__all__ = [
    "ContractValue",
    "Diagnostic",
    "ErrorClassification",
    "ErrorKind",
    "IdempotencyMetadata",
    "RetryDisposition",
    "ReviewDecision",
    "ReviewStatus",
    "SpecialistResult",
    "SpecialistResultStatus",
    "SpecialistTask",
    "TaskContext",
    "WorkflowMode",
    "build_idempotency_key",
    "classify_error",
    "fingerprint_inputs",
    "sanitize_diagnostic",
    "validate_specialist_result",
]
