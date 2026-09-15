# Architectural Decisions

Records important decisions that affect future implementation.

---

## DECISION-001

Date:
2026-09-15

Decision:
Use WebSocket for live delivery tracking.

Reason:
Live location does not require persistence; WebSocket provides low-latency updates.

Persistence:
Database stores tracking history and orders.

Status:
ACTIVE

---

## DECISION-002

Date:
2026-09-16

Decision:
Adopt feature-based folders + Repository pattern with Riverpod.

Reason:
Keeps features isolated, allows swapping Firebase for another DB later.

Status:
ACTIVE

---

## DECISION-003

Date:
2026-09-20

Decision:
REST via Next.js API routes (not GraphQL).

Reason:
Team familiarity and simple CRUD for MVP; revisit if client needs flexible queries.

Status:
ACTIVE

---

## DECISION-004

Date:
2026-09-22

Decision:
Do NOT introduce microservices / event bus at MVP stage.

Reason:
Single-deploy simplicity outweighs scalability benefits now. Revisit at >10k daily deliveries.

Status:
ACTIVE
