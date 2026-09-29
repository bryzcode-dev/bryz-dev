class ProjectOSError(Exception):
    """Base class for expected ProjectOS errors."""


class MigrationError(ProjectOSError):
    """Raised when a database migration cannot be applied safely."""


class ValidationError(ProjectOSError):
    """Raised when input violates a domain invariant."""


class VersionConflict(ProjectOSError):
    """Raised when optimistic concurrency detects a stale writer."""


class HealthError(ProjectOSError):
    """Raised when an integrity or health gate fails."""

