"""Harmless public capability query for the P00 platform spike."""

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def default_tools() -> list[Literal["get_capabilities"]]:
    return ["get_capabilities"]


class CapabilitiesData(BaseModel):
    """Capabilities that are actually enabled in the current release."""

    model_config = ConfigDict(extra="forbid")

    server_name: Literal["swim-coach"] = "swim-coach"
    server_version: Literal["0.0.0-spike"] = "0.0.0-spike"
    phase: Literal["P00"] = "P00"
    release_mode: Literal["platform-feasibility"] = "platform-feasibility"
    available_tools: list[Literal["get_capabilities"]] = Field(default_factory=default_tools)
    transport: Literal["streamable-http"] = "streamable-http"
    private_training_data_enabled: Literal[False] = False
    garmin_read_enabled: Literal[False] = False
    garmin_write_enabled: Literal[False] = False
    custom_ui_enabled: Literal[False] = False
    limitations: list[str] = Field(
        default_factory=lambda: [
            "P00 exposes no athlete or activity data.",
            "OAuth and Garmin are feasibility probes, not enabled product capabilities.",
            "No tool in this release performs a write or external side effect.",
        ]
    )


class CapabilityResult(BaseModel):
    """Versioned MCP result envelope."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    request_id: str
    status: Literal["OK"] = "OK"
    data: CapabilitiesData
    warnings: list[dict[str, str]] = Field(default_factory=list)
    next_actions: list[dict[str, str]] = Field(default_factory=list)
    human_summary: str


def get_capabilities() -> CapabilityResult:
    """Return only the capabilities proven safe and available in P00."""

    return CapabilityResult(
        request_id=f"req_{uuid4().hex}",
        data=CapabilitiesData(),
        human_summary=(
            "Swim Coach P00 is connected with one harmless read-only capability check; "
            "private data, Garmin access, writes, and custom UI are disabled."
        ),
    )
