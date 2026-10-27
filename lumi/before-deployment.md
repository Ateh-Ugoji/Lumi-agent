# Before Deployment Checklist

Things changed or set up for local testing that need attention before deploying.

## PFM Callback URL

- **Local testing**: The PFM dashboard redirect URL was set to the localtunnel URL (`https://<subdomain>.loca.lt/pfm/callback`) for local OAuth testing.
- **Before deploy**: Update the PFM dashboard redirect URL to point to your production domain: `https://<your-railway-domain>/pfm/callback`

## Environment Variables

- **Local**: `.env` file at repo root with all keys filled in.
- **Before deploy**: Ensure all env vars are set in Railway dashboard:
  - `DATABASE_URL` — Railway Postgres connection string (Railway provides this automatically)
  - `PFM_JWT_TOKEN`
  - `XPOZ_API_KEY`
  - `GROQ_API_KEY`
  - `OPENROUTER_API_KEY`
  - `TYPESAFE_API_KEY`
  - `NEATLOGS_API_KEY`
  - `SECRET_KEY`
- **IMPORTANT**: Rotate all API keys — they were exposed in a conversation context. Generate new keys for production.

## Database

- **Local**: Docker container `lumi-postgres` running on `localhost:5432` with credentials `lumi:lumi`.
- **Before deploy**: Railway Postgres service handles this. Run `alembic upgrade head` on first deploy.

## Localtunnel

- **Local**: `npx localtunnel --port 8000` was used to expose the backend for PFM OAuth redirects.
- **Before deploy**: Kill the tunnel. Not needed in production — Railway provides a public URL.

## Entire Graph

- `GRAPH_REPORT.md` was generated for the hackathon submission. Safe to keep or remove.
- `.entire/graph-agent.md` and `AGENTS.md` were added by `entire graph init-agents`. Keep them — they help coding agents use the graph.

## No Code Changes to Revert

No URLs, ports, or config values were hardcoded for local testing. All environment-specific values come from `.env` / Railway env vars, so the code deploys as-is.
