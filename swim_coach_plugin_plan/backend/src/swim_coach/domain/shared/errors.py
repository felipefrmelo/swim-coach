"""Stable domain errors independent from transport concerns."""

from collections.abc import Mapping


class DomainError(Exception):
    """Base error with a stable public code and sanitized details."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, str | int | bool] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


class DomainValidationError(DomainError):
    """Raised when a domain invariant is violated."""

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, str | int | bool] | None = None,
    ) -> None:
        super().__init__("VALIDATION_FAILED", message, details=details)


class ResourceNotFoundError(DomainError):
    """Ownership-safe not-found error."""

    def __init__(self, resource: str) -> None:
        super().__init__(
            "RESOURCE_NOT_FOUND",
            "The requested resource was not found.",
            details={"resource": resource},
        )


class RevisionConflictError(DomainError):
    """Raised on failed optimistic concurrency checks."""

    def __init__(self, current_version: int) -> None:
        super().__init__(
            "REVISION_CONFLICT",
            "The resource changed since it was loaded.",
            details={"current_version": current_version},
        )
