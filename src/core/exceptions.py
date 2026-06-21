"""Custom exception hierarchy for the competitive replay analysis system.

A dedicated exception tree allows the business-logic layer to react to
specific failure modes (for instance retrying a single failed analysis
segment) without relying on string matching.
"""


class ReplayError(Exception):
    """Base class for every error raised inside the application."""


class VideoProcessingError(ReplayError):
    """Raised when a recording cannot be decoded or preprocessed."""


class VisionDetectionError(ReplayError):
    """Raised when the UI-element detector fails for a frame."""


class AnalysisError(ReplayError):
    """Raised when the decision-analysis layer cannot produce a result."""


class LLMUnavailableError(AnalysisError):
    """Raised when no local multimodal LLM backend is reachable."""


class ReportGenerationError(ReplayError):
    """Raised when an HTML report cannot be assembled or written."""


class DatabaseError(ReplayError):
    """Raised on SQLite-level failures (corruption, locked, schema)."""


class ConfigError(ReplayError):
    """Raised when configuration values are invalid or missing."""


class PluginError(ReplayError):
    """Raised by the plugin manager when loading/executing a plugin fails."""
