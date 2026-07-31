"""Safe application errors exposed through the HTTP boundary."""


class AppError(Exception):
    """Base error carrying a stable public code and HTTP status."""

    code = "INTERNAL_ERROR"
    status_code = 500
    default_message = "The request could not be completed."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class TenantContextRequiredError(AppError):
    code = "TENANT_CONTEXT_REQUIRED"
    status_code = 401
    default_message = "A trusted tenant context is required."


class TenantContextMismatchError(AppError):
    code = "TENANT_CONTEXT_MISMATCH"
    status_code = 401
    default_message = "The supplied tenant identity is not accepted."


class ResourceNotFoundError(AppError):
    code = "NOT_FOUND"
    status_code = 404
    default_message = "The requested resource was not found."


class FeatureNotAvailableError(AppError):
    code = "FEATURE_NOT_AVAILABLE"
    status_code = 501
    default_message = "This memory capability is not implemented yet."


class VersionConflictError(AppError):
    code = "VERSION_CONFLICT"
    status_code = 409
    default_message = "The active memory version changed during governance."
