# Self-Created Agents Report

Phase: 17

## Status

- Self-created agent system: safely scaffolded.
- Default flag: `JARVIS_AGENT_MODE=0`.
- Agent definitions are data only, not executable code.
- User approval is required before enabling an agent.

## Implemented

- `app/agents/agent_definition.py`
- `app/agents/agent_builder.py`
- `app/agents/agent_registry.py`
- `app/repositories/agent_repository.py`
- `tests/test_agent_builder.py`
- `tests/test_agent_registry.py`

## Safety

- Unsafe tools such as terminal, code edit, Gmail, WhatsApp, message, and phone are rejected from default agent drafts.
- Disabled agents do not run.
- Allowed tools are enforced before a run can be queued.
- Scheduled/background execution is not silently enabled.

## Deferred

- Actual scheduled execution.
- Agent report ingestion into notification center.
- LangGraph-backed execution beyond disabled scaffolding.
