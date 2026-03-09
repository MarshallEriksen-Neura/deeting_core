import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

McpServerType = Literal["sse", "stdio"]
McpAvailabilityLane = Literal["callable_now", "installable", "advisory"]
McpIndexStatus = Literal["indexed", "missing", "unknown"]


def _tool_names(payloads: list[dict] | None) -> list[str]:
    names: list[str] = []
    for item in payloads or []:
        name = str(item.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _enabled_tool_names(model: Any) -> set[str]:
    disabled = set(model.disabled_tools or [])
    return {name for name in _tool_names(model.tools_cache) if name not in disabled}


def _derive_index_status(
    expected_names: set[str],
    indexed_tool_names: set[str] | None,
) -> tuple[McpIndexStatus, str | None]:
    if indexed_tool_names is None:
        return "unknown", "index_unavailable"
    if not expected_names:
        return "unknown", None
    if expected_names.issubset(indexed_tool_names):
        return "indexed", None
    return "missing", "index_missing"


def _derive_server_recommended_action(
    *,
    model: Any,
    runtime_ready: bool,
    index_status: McpIndexStatus,
) -> str | None:
    if model.server_type != "sse":
        return None
    if not model.is_enabled:
        return "enable_server"
    if not runtime_ready or index_status == "missing":
        return "sync_server"
    return None


class UserMcpServerBase(BaseModel):
    name: str = Field(
        ..., max_length=120, description="Display name for the MCP server"
    )
    description: str | None = Field(None, description="Optional description")
    sse_url: HttpUrl | None = Field(
        None, description="Full URL to the MCP SSE endpoint"
    )
    is_enabled: bool = Field(True, description="Whether the server is enabled")
    server_type: McpServerType = Field(
        "sse", description="Server type: sse (remote) or stdio (draft)"
    )
    auth_type: str = Field("bearer", description="bearer, api_key, or none")


class UserMcpServerCreate(UserMcpServerBase):
    """Schema for creating a new MCP server configuration."""

    secret_value: str | None = Field(
        None, description="The actual API Key/Token value (write-only)"
    )
    draft_config: dict[str, Any] | None = Field(
        None, description="Sanitized draft config for stdio imports"
    )


class UserMcpServerUpdate(BaseModel):
    """Schema for updating an existing MCP server."""

    name: str | None = Field(None, max_length=120)
    description: str | None = None
    sse_url: HttpUrl | None = None
    is_enabled: bool | None = None
    server_type: McpServerType | None = None
    auth_type: str | None = None
    secret_value: str | None = None
    draft_config: dict[str, Any] | None = None


class UserMcpServerResponse(UserMcpServerBase):
    """Schema for returning MCP server details."""

    id: uuid.UUID
    user_id: uuid.UUID
    source_id: uuid.UUID | None = None
    source_key: str | None = None
    created_at: Any
    updated_at: Any
    secret_ref_id: str | None = Field(
        None, description="Reference ID for the stored secret"
    )
    tools_count: int = Field(0, description="Number of cached tools")
    status: str = Field("unknown", description="Sync status: active, error, unknown")
    desired_enabled: bool = Field(True, description="Desired/config enabled state")
    runtime_ready: bool = Field(False, description="Whether this server is runtime-ready")
    runtime_status_reason: str | None = Field(
        None, description="Reason when runtime is not ready"
    )
    availability_lane: McpAvailabilityLane = Field(
        "advisory", description="Availability lane for UI consumption"
    )
    recommended_action: str | None = Field(
        None, description="Suggested next UI action"
    )
    activation_required: bool = Field(
        False, description="Whether activation is required before use"
    )
    install_required: bool = Field(
        False, description="Whether installation/import is required before use"
    )
    index_status: McpIndexStatus = Field(
        "unknown", description="Derived retrieval/index exposure status"
    )
    index_status_reason: str | None = Field(
        None, description="Reason for current index status"
    )

    model_config = ConfigDict(from_attributes=True)

    @staticmethod
    def from_orm_model(
        model: Any,
        indexed_tool_names: set[str] | None = None,
    ) -> "UserMcpServerResponse":
        count = len(model.tools_cache) if model.tools_cache else 0
        enabled_tool_names = _enabled_tool_names(model) if model.is_enabled else set()
        runtime_ready = bool(
            model.server_type == "sse" and model.is_enabled and count > 0
        )
        if model.server_type == "stdio":
            runtime_status_reason = "draft_config"
        elif not model.is_enabled:
            runtime_status_reason = "disabled"
        elif count == 0:
            runtime_status_reason = "no_cached_tools"
        else:
            runtime_status_reason = None
        availability_lane: McpAvailabilityLane = (
            "callable_now"
            if runtime_ready
            else ("installable" if model.server_type == "stdio" else "advisory")
        )
        index_status, index_status_reason = _derive_index_status(
            enabled_tool_names,
            indexed_tool_names,
        )
        recommended_action = _derive_server_recommended_action(
            model=model,
            runtime_ready=runtime_ready,
            index_status=index_status,
        )
        return UserMcpServerResponse(
            id=model.id,
            user_id=model.user_id,
            source_id=getattr(model, "source_id", None),
            source_key=getattr(model, "source_key", None),
            name=model.name,
            description=model.description,
            sse_url=model.sse_url,
            is_enabled=model.is_enabled,
            server_type=model.server_type,
            auth_type=model.auth_type,
            created_at=model.created_at,
            updated_at=model.updated_at,
            secret_ref_id=model.secret_ref_id,
            tools_count=count,
            status=(
                "draft"
                if model.server_type == "stdio"
                else ("active" if model.is_enabled and count > 0 else "inactive")
            ),
            desired_enabled=model.is_enabled,
            runtime_ready=runtime_ready,
            runtime_status_reason=runtime_status_reason,
            availability_lane=availability_lane,
            recommended_action=recommended_action,
            activation_required=bool(model.server_type == "sse" and not model.is_enabled),
            install_required=bool(model.server_type == "stdio"),
            index_status=index_status,
            index_status_reason=index_status_reason,
        )


class McpServerToolItem(BaseModel):
    name: str = Field(..., description="Tool name")
    description: str | None = Field(None, description="Tool description")
    input_schema: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema for tool arguments"
    )
    enabled: bool = Field(True, description="Whether this tool is enabled")
    desired_enabled: bool = Field(True, description="Desired/config enabled state")
    runtime_ready: bool = Field(False, description="Whether this tool is runtime-ready")
    runtime_status_reason: str | None = Field(
        None, description="Reason when runtime is not ready"
    )
    availability_lane: McpAvailabilityLane = Field(
        "advisory", description="Availability lane for UI consumption"
    )
    recommended_action: str | None = Field(
        None, description="Suggested next UI action"
    )
    activation_required: bool = Field(
        False, description="Whether activation is required before use"
    )
    install_required: bool = Field(
        False, description="Whether installation/import is required before use"
    )
    index_status: McpIndexStatus = Field(
        "unknown", description="Derived retrieval/index exposure status"
    )
    index_status_reason: str | None = Field(
        None, description="Reason for current index status"
    )

    @staticmethod
    def from_cached_tool(
        *,
        server_model: Any,
        tool_payload: dict[str, Any],
        indexed_tool_names: set[str] | None = None,
    ) -> "McpServerToolItem":
        name = str(tool_payload.get("name") or "").strip()
        disabled = set(server_model.disabled_tools or [])
        enabled = name not in disabled
        runtime_ready = bool(
            name
            and enabled
            and server_model.server_type == "sse"
            and server_model.is_enabled
        )
        if server_model.server_type == "stdio":
            runtime_status_reason = "draft_config"
        elif not enabled:
            runtime_status_reason = "tool_disabled"
        elif not server_model.is_enabled:
            runtime_status_reason = "server_disabled"
        else:
            runtime_status_reason = None
        availability_lane: McpAvailabilityLane = (
            "callable_now"
            if runtime_ready
            else (
                "installable"
                if server_model.server_type == "stdio"
                else "advisory"
            )
        )
        index_status, index_status_reason = _derive_index_status(
            {name} if enabled and server_model.is_enabled and name else set(),
            indexed_tool_names,
        )
        return McpServerToolItem(
            name=name,
            description=tool_payload.get("description"),
            input_schema=tool_payload.get("input_schema") or {},
            enabled=enabled,
            desired_enabled=enabled,
            runtime_ready=runtime_ready,
            runtime_status_reason=runtime_status_reason,
            availability_lane=availability_lane,
            recommended_action=(
                "wait_for_runtime"
                if enabled
                and server_model.server_type == "sse"
                and not server_model.is_enabled
                else None
            ),
            activation_required=bool(
                enabled
                and server_model.server_type == "sse"
                and not server_model.is_enabled
            ),
            install_required=bool(server_model.server_type == "stdio"),
            index_status=index_status,
            index_status_reason=index_status_reason,
        )


class McpServerToolToggleRequest(BaseModel):
    enabled: bool = Field(..., description="Whether to enable this tool")


class McpToolTestRequest(BaseModel):
    server_id: uuid.UUID
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class McpToolTestResponse(BaseModel):
    status: Literal["success", "error"]
    result: Any | None = None
    error: str | None = None
    logs: list[str] = Field(default_factory=list)
    trace_id: str
