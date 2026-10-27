# Docs

Short, logic-focused notes per module — why things are built the way they are, and the gotchas you'd otherwise find by breaking them. For the big picture (stack, request flow, full table list), read [../README.md](../README.md) and [../CLAUDE.md](../CLAUDE.md) first. For the planning specs this build follows, see [`../.agents/`](../.agents/).

- [models.md](models.md) — the 11 tables, and the non-obvious invariants (voice versioning, alert-once, `posts` vs `listening_matches`)
- [routers.md](routers.md) — the HTTP endpoints and what they're responsible for
- [tools.md](tools.md) — agent-callable functions, how registration works, one gotcha per tool
- [agent.md](agent.md) — the chat loop, persona prompt, profile-context injection, provider fallback, tracing
- [services.md](services.md) — shared logic: PFM client + backfill, velocity math, enforcement pipeline, difficulty routing
- [background.md](background.md) — the polling loop + profile bootstrap (voice profile + peer frameworks)
- [flow-map.md](flow-map.md) — whole-app mermaid flow (connect → voice → peer frameworks → chat), keep in sync when adding tools/routers ([flow-map.html](flow-map.html) — same map as a clickable page)
- [mcp-connectors.md](mcp-connectors.md) — the MCP connector layer (Google Drive/Docs first): architecture, the one-entry recipe for adding another connector, the manual Google Cloud setup checklist, and the live verification script
- [frontend-integration.md](frontend-integration.md) — for whoever's building the frontend: base URL, every endpoint's exact shape, the PFM connect-flow handoff, and what's actually working on the live deployment right now vs. what still 500s

Each file is meant to be read in under two minutes. If a module's logic needs more than that to explain, the code probably needs a comment, not a longer doc.
