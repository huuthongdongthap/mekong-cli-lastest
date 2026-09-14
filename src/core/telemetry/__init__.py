# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""
core/telemetry — Telemetry package (legacy re-exports + OpenTelemetry wiring).

Public API:
  # New (Layer 2 — OpenTelemetry agent instrumentation)
  from src.core.telemetry import observe_agent
  from src.core.telemetry.meters import METERS
  from src.core.telemetry.gpu_probe import GpuProbe

  # Legacy (preserved for backwards compatibility after package migration)
  from src.core.telemetry import TelemetryCollector, ExecutionTrace, ...
"""

# Layer 2 — OpenTelemetry SDK wiring
from src.core.telemetry.instrument import observe_agent

# Legacy re-exports (preserved from src/core/telemetry.py prior to package conversion)
from src.core.telemetry_collector import TelemetryCollector
from src.core.telemetry_models import (
    ExecutionTrace,
    StepTrace,
    SubsystemHealth,
    SubsystemHealthReport,
)
from src.core.tiered_store import TieredTelemetryStore
from src.core.event_bus import EventType

from src.core.license_monitor import (
    LicenseMonitor,
    LicenseFailure,
    FailureThreshold,
    get_monitor,
    record_failure,
)

from src.core.anomaly_detector import (
    Anomaly,
    AnomalyCategory,
    AnomalyType,
    BaselineStats,
    UsageAnomalyDetector,
    get_detector,
)
from src.core.usage_metering import (
    UsageEvent,
    UsageEventType,
    UsageMetering,
    get_metering,
    reset_metering,
)

__all__ = [
    # Layer 2 OTel
    "observe_agent",
    # Legacy models
    "ExecutionTrace",
    "StepTrace",
    "SubsystemHealth",
    "SubsystemHealthReport",
    "TelemetryCollector",
    "TieredTelemetryStore",
    "EventType",
    # License monitoring
    "LicenseMonitor",
    "LicenseFailure",
    "FailureThreshold",
    "get_monitor",
    "record_failure",
    # Usage anomaly detection
    "Anomaly",
    "AnomalyCategory",
    "AnomalyType",
    "BaselineStats",
    "UsageAnomalyDetector",
    "get_detector",
    "UsageEvent",
    "UsageEventType",
    "UsageMetering",
    "get_metering",
    "reset_metering",
]
