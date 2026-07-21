"""AgenticLogger — Structured logging for Coding Agents.

Thin re-export module. Detailed API docs live inline in each submodule,
referenced back to the architecture spec via ``@spec-ref``.

@spec-ref: spec/03-write-sdk.md — Write SDK API Design
@spec-ref: spec/01-architecture.md — System Architecture
@last-changed: 2026-07-21
"""

from agentic_logger.logger import AgentLogger
from agentic_logger.error_codes import ErrorCode

__all__ = ["AgentLogger", "ErrorCode"]
__version__ = "0.1.0"
