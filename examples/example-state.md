# Vibe State

## Project
Name: delivery-tracker
Purpose: Live delivery tracking for small logistics teams
Current stage: MVP / prototype

## Architecture
Pattern: feature-based + repository
Backend: express-like routes, fetch/axios
Frontend: React / Next.js
Database: firebase
State management: riverpod

## Design Language
Style: Material 3
Spacing: 8pt grid
Typography: Inter, 14/20 base
Component philosophy: feature-based atomic components

## Coding Preferences
Naming: camelCase (JS/TS)
File organization: feature-based folders (lib/features/*)
Error handling: try/catch + zod validation
Testing philosophy: critical-path coverage

## Important Decisions
- Architecture pattern: feature-based + repository
- State management: Riverpod
- Database: Firebase Firestore (live location not persisted; history in Postgres)
- API: REST via Next.js API routes
- Auth: Firebase Auth behind repository boundary

## Current Focus
Implement live map tracking with WebSocket updates

## Known Constraints
- Keep velocity high; avoid premature abstraction
- Offline support required for next stage

## Active Technical Debt
2 open items

## Don't Break
- Existing feature-based + repository organization
- State management: riverpod
- Database: firebase
- Don't hardcode secrets into UI

## Next Likely Direction
Hardening for production: persistent tracking history, role-based access
