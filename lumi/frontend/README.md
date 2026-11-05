# Lumi Frontend

Modern, high-performance React SPA for Lumi — the AI social media intelligence agent. Built with React 19, TypeScript, and Vite.

---

## 1. Stack & Architecture

- **Core**: React 19, TypeScript 5.7+, Vite 6
- **Routing & Views**: State-driven navigation (`chat`, `chronic`, `publish`, `settings`)
- **Styling**: Modern CSS Modules with CSS variables, glassy surfaces, and fluid micro-animations
- **State Management**: Reactive hooks (`useProfiles`, `useLightMode`, `useVoiceInput`) with persistent session storage
- **Real-Time Communications**:
  - SSE Streaming Chat via `/api/v1/chat/stream`
  - Real-time tool-execution activity tracker
  - Native Voice STT audio recording & waveform rendering
- **Internationalization**: Lightweight typed i18n system (`en` and `es`)

---

## 2. Directory Structure

```
frontend/src/
├── api/                  # Typed API clients (chat, connections, profiles, publish, jobs)
├── components/
│   ├── AccountUnderstandingModal/ # 5-stage competitor and framework extraction visualizer
│   ├── ConnectSocialsModal/       # Social OAuth modal with quick-sync and PFM guidance
│   ├── ChronicOnline/             # Real-time viral trends radar and repurpose pipeline
│   ├── PublishStudio/             # Multi-platform post composer, preview, and publisher
│   ├── Settings/                  # Profile settings, ConnectionsPanel, and MCP connectors
│   ├── Sidebar/                   # Workspace switcher, profile selector, chat history
│   ├── ThinkingState/             # Animated tool execution and status badges
│   └── VoiceMode/                 # Interactive audio recording and speech waveform
├── hooks/                # Custom React hooks (useProfiles, useLightMode)
├── i18n/                 # Locale dictionaries and translation hook (useT)
└── App.tsx               # Root application coordinator and OAuth callback landing
```

---

## 3. Key Flows

### A. OAuth Callback & Account Synchronization
1. When authenticating with Twitter, LinkedIn, or Meta via Post for Me, the callback lands on `/connections/pfm/callback`.
2. `App.tsx` captures the callback via `parseCallbackLanding`, silently resets the browser URL to `/`, and calls `finishConnect`.
3. If connected, it triggers `AccountUnderstandingModal` to visually showcase creator persona ingestion, competitor discovery, and framework acquisition.
4. **Manual Sync**: If Post for Me redirected to another project (e.g. Onscript), the user can click **"Sync Accounts"** in `ConnectSocialsModal` or Settings to pull their accounts without re-doing OAuth.

### B. Account Disconnection
- Accounts can be disconnected directly from **Settings → Connected Accounts** (`ConnectionsPanel`) or via the **Workspace Menu** on the sidebar.
- Disconnecting revokes tokens remotely (best effort) and removes the account credentials from the local database.

---

## 4. Running Locally

```bash
# Install dependencies
npm install

# Start Vite dev server on port 3010
npm run dev -- --port 3010

# Typecheck TypeScript without emitting
npm run typecheck

# Production build
npm run build
```

The dev server proxies API calls to the Django ASGI backend running at `http://127.0.0.1:8000`.
