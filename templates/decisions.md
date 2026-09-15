# Architectural Decisions

Records important decisions that affect future implementation.
Only decisions that impact future work are stored — not trivial choices.

---

## DECISION-001

Date:
2026-09-15

Decision:
Use WebSocket for live delivery tracking.

Reason:
Live location does not require persistence.

Persistence:
Database stores tracking history and orders.

Status:
ACTIVE

---

## DECISION-002

Date:
2026-09-15

Decision:
Use Riverpod + Repository pattern with feature-based folders.

Reason:
Consistent state management and separation of concerns for the project's expected next stage.

Status:
ACTIVE
