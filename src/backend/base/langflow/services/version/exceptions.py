class VersioningError(Exception):
    """Base exception for versioning related errors."""


class VersionNotFoundError(VersioningError):
    """Raised when a requested version cannot be found."""


class ActiveVersionNotSetError(VersioningError):
    """Raised when a flow does not have an active version defined."""


class VersionImmutableError(VersioningError):
    """Raised when attempting to mutate an immutable published version."""


class InvalidVersionOperationError(VersioningError):
    """Raised when an invalid operation is requested for the current version state."""


class VersionConflictError(VersioningError):
    """Raised when there is a conflict with existing version data."""
