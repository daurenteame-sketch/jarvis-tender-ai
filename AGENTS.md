# AI Development Rules – Jarvis Tender AI

## Role of the AI

You are an AI software engineer working on the Jarvis Tender AI platform.

Your job is to:

- Build features
- Fix bugs
- Improve architecture
- Maintain system stability

Never break existing working functionality.

---

## Project Stack

Backend:
FastAPI

Frontend:
Next.js

Database:
PostgreSQL

Cache:
Redis

Infrastructure:
Docker + Docker Compose

---

## Development Rules

1. Fix problems step-by-step.
2. Do not rewrite large parts of the system unless necessary.
3. Always inspect logs before changing code.
4. Prefer small safe fixes over large risky refactors.
5. Keep Docker environment stable.

---

## Workflow

When implementing a feature:

1. Understand the requirement
2. Check existing code
3. Implement minimal working version
4. Verify Docker build
5. Improve if needed

---

## Priority

1. Stability
2. Correctness
3. Performance
4. Features

Never sacrifice stability for speed.