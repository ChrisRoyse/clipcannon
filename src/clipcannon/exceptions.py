"""Custom exception hierarchy for ClipCannon.

All ClipCannon-specific exceptions inherit from ClipCannonError,
enabling callers to catch the base class for broad handling or
specific subclasses for targeted recovery.
"""


class ClipCannonError(Exception):
    """Base exception for all ClipCannon errors.

    Attributes:
        message: Human-readable error description.
        details: Optional structured data providing additional context.
    """

    def __init__(self, message: str, details: dict[str, str | int | float | bool | None] | None = None) -> None:
        """Initialize ClipCannonError.

        Args:
            message: Human-readable error description.
            details: Optional structured data providing additional context.
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}


class PipelineError(ClipCannonError):
    """Raised when a pipeline stage fails.

    Attributes:
        stage_name: Name of the pipeline stage that failed.
        operation: The provenance operation identifier.
    """

    def __init__(
        self,
        message: str,
        stage_name: str = "",
        operation: str = "",
        details: dict[str, str | int | float | bool | None] | None = None,
    ) -> None:
        """Initialize PipelineError.

        Args:
            message: Human-readable error description.
            stage_name: Name of the pipeline stage that failed.
            operation: The provenance operation identifier.
            details: Optional structured data providing additional context.
        """
        super().__init__(message, details)
        self.stage_name = stage_name
        self.operation = operation


class BillingError(ClipCannonError):
    """Raised when a billing or credit operation fails.

    Covers credit checks, charges, refunds, HMAC validation,
    and communication with the license server or Stripe.
    """


class ProvenanceError(ClipCannonError):
    """Raised when provenance chain operations fail.

    Covers hash computation, chain verification, record insertion,
    and tamper detection.
    """


class DatabaseError(ClipCannonError):
    """Raised when database operations fail.

    Covers connection issues, schema creation, query execution,
    extension loading (sqlite-vec), and migration errors.
    """


class ConfigError(ClipCannonError):
    """Raised when configuration loading, parsing, or validation fails.

    Covers missing config files, invalid values, type mismatches,
    and unsupported configuration keys.
    """


class GPUError(ClipCannonError):
    """Raised when GPU operations fail.

    Covers device detection failures, VRAM exhaustion,
    model loading failures, and precision auto-selection errors.
    """
