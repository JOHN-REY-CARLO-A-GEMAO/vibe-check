# Technical Debt Ledger

This file tracks intentional shortcuts that could affect future development.
Only meaningful debt is recorded - not every minor imperfection.

## How to use
- Status: OPEN, MONITORING, RESOLVED, ACCEPTED
- Priority = Impact × Likelihood × Migration Cost

---

## DEBT-001

Title:
Hardcoded authentication

Created:
2026-09-15

Location:
lib/auth/login.dart

Why it exists:
Temporary shortcut during MVP development.

Risk:
Medium

Future trigger:
Replace with production authentication.

Estimated rework:
2–4 hours

Status:
OPEN

---

## DEBT-002

Title:
Direct Firebase calls in UI components

Created:
2026-09-16

Location:
lib/features/tracking/map_widget.dart

Why it exists:
Fastest way to show live location without service layer.

Risk:
High

Future trigger:
Extract to TrackingRepository before adding offline support.

Estimated rework:
4–6 hours

Status:
OPEN

---

## DEBT-003

Title:
Duplicated validation for delivery address

Created:
2026-09-18

Location:
lib/features/order/form.dart, api/orders/validate.js

Why it exists:
Copied validation for speed.

Risk:
Medium

Future trigger:
Consolidate with zod schema when adding new address fields.

Estimated rework:
1–2 hours

Status:
MONITORING

---

## DEBT-004

Title:
Oversized order service (620 lines)

Created:
2026-09-20

Location:
lib/services/order_service.dart

Why it exists:
Feature grew organically.

Risk:
High

Future trigger:
Split before adding payment flow.

Estimated rework:
3–5 hours

Status:
OPEN
