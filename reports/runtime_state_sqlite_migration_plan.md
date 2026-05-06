# Runtime State SQLite Migration Plan

Date: 2026-05-06

## Current State

`app/state/runtime_state.py` already provides SQLite-backed storage for sessions, turns, policy decisions, execution events, audit events, and pending confirmations. Several older services still persist JSON/runtime files directly under `database/`.

## Move To SQLite Later

- Chat sessions and turns currently persisted as JSON chat files.
- Pending confirmations and authorization prompts that still live in service memory or JSON files.
- Tool execution audit logs and policy decisions not already written through `RuntimeStateStore`.
- Agent task metadata currently stored in `database/agent_tasks`.
- Memory index metadata and retrieval manifests where the data is small and structured.
- Observability event summaries when they need queryability or retention policy.

## Keep File Or Blob Based

- Camera captures and screenshots.
- Audio recordings and voice samples.
- Attachments or generated media.
- FAISS/vector index binaries and large embedding stores unless a dedicated vector database is chosen.
- Model files and provider caches.

## Recommended Sequence

1. Add repository interfaces for chat sessions, agent tasks, memory metadata, and observability events.
2. Back each repository with SQLite while keeping existing JSON readers as import/compatibility adapters.
3. Add migration tests using temporary SQLite databases and fixture JSON files.
4. Migrate one state family at a time; do not mix data migration with automation boundary refactors.
5. Only archive old JSON/runtime folders after tests prove round-trip compatibility and the runtime no longer writes them.

No database migration is performed in this phase.
