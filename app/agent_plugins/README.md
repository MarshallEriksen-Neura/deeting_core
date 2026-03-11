# Agent Plugins

This directory contains the backend host/runtime plugin layer for AI Agents, migrated from `backend_old`.

## Structure

- **core/**: Core interfaces and managers (`PluginManager`, `AgentPlugin`, `PluginContext`).
- **builtins/**: Built-in host/runtime plugins (e.g., Provider Registry, Crawler).
- **examples/**: Example plugins (e.g., `HelloWorldPlugin`).

## Creating a New Host Plugin

1. Inherit from `app.agent_plugins.core.interfaces.AgentPlugin`.
2. Implement `metadata` and `get_tools` (optional).
3. Implement `async def on_activate(self)` and `async def on_deactivate(self)` if needed.
4. If you expose tools, implement the corresponding handler methods (convention: `handle_<tool_name>`).

## Usage

Host/runtime plugins are managed by `app.agent_plugins.core.manager.PluginManager`.
