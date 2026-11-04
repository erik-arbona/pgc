# PGC

Coordination management platform (DSD and exam calendar) for Uni-CV. See `CLAUDE.md` and `docs/`.

## Quick start (Docker)

```bash
cp .env.example .env          # then edit secrets
docker compose up --build
docker compose exec web pytest
```

The app is served at http://localhost:8000. Settings are read from environment variables (see `.env.example`).
