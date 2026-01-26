# Core Infrastructure — Mandatory PAUSE Protocol

- **Doc**: Tech_Plan__Core_Infrastructure/09_Mandatory_Pause_Protocol.md
- **Updated**: 2026-01-26
- **Library**: `workflow_engine.control.pause`
- **Depends on**: [`00_Foundation.md`](00_Foundation.md), [`06_Durability_Protocol.md`](06_Durability_Protocol.md), [`07_Logs_Store.md`](07_Logs_Store.md), [`08_Queues_Notifications_and_Control_Actions.md`](08_Queues_Notifications_and_Control_Actions.md)
- **Primary responsibility**: Define the system-wide PAUSE contract that must be durable, auditable, and safe across tools/subprocesses.

## 10) Mandatory PAUSE protocol (core contract)

A step is paused iff:
1. no tool subprocesses running
2. no WSS mutation in progress
3. control loop is waiting for RESUME/STOP
4. logs flushed to a safe boundary
5. ACK written under `control_actions/ack/`

Exact action/ACK shapes and flow are specified in Core Flows.

