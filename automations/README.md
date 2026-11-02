# Lumi Niche Radar & Email Alerts (n8n Automation)

> **Workflow File**: [`lumi_niche_radar_workflow.json`](./lumi_niche_radar_workflow.json)  
> **Original Prototype**: [`c:\Users\USER\Downloads\n8n Lumi.txt`](file:///c:/Users/USER/Downloads/n8n%20Lumi.txt)  
> **Master Architecture Plan**: [`../automation.md`](../automation.md)  

---

## 1. Overview

This automation elevates the baseline social listening script into a **full production intelligence pipeline**:
1. **Dynamic Niche Keywords**: Queries are parameterized dynamically instead of hardcoding a single query.
2. **Multi-Platform Live Search**: Fetches live data across **X (Twitter)**, **TikTok**, **Instagram**, and **Reddit** via Xpoz.ai concurrently.
3. **Lumi `PostStats` Schema Normalization**: Standardizes heterogenous platform responses into Lumi's production schema, calculating engagement totals, engagement rates, and accurate publication timestamps (including TikTok snowflake decoding and Reddit permalink canonicalization).
4. **Outlier & Winner Detection**: Computes median engagement across all scraped posts, measures `outlier_score` (multiplier vs baseline), and filters winning content (`outlier >= 1.5x`).
5. **Cognitive Post Frameworks (Lumi AI)**:
   - **Hook Types**: Contrarian, Curiosity Gap, Stat Shock, Pain Callout, Result Claim, How-To Promise.
   - **Frameworks**: Problem-Agitate-Solution (PAS), Attention-Interest-Desire-Action (AIDA), Before-After-Bridge (BAB), Story Arc, Listicle, Tutorial.
   - **Viral Reasons & Remix Angles**: Generates actionable insight on why the post performed and how the creator can adapt it in their voice.
6. **Responsive HTML Email Digest**: Sends a dark-mode email alert to the user's inbox with metric pills, hook spotlights, and direct 1-click action buttons ("View Original" and "Remix in my Voice with Lumi").
7. **Lumi Ingestion Sync**: Automatically syncs discovered framework winners into Lumi's PostgreSQL database (`NicheReport`, `Framework`, `FrameworkEvidence`, `Post`, `MetricSnapshot`).

---

## 2. Quickstart & Import into n8n

### Step 1: Import Workflow
1. Open your n8n dashboard (e.g. `http://localhost:5678`).
2. Click **Add workflow** $\rightarrow$ Click the **three dots (⋮)** menu $\rightarrow$ **Import from File**.
3. Select `automations/lumi_niche_radar_workflow.json`.

### Step 2: Configure Credentials
1. **Xpoz.ai API**: Ensure the generic HTTP Auth credential `Xpoz Access Key (Christian F)` has your Xpoz Access Key (Header: `x-access-key` or query parameter).
2. **Email Sender**: In the `Send Email Alert` node, configure your SMTP server, Gmail OAuth, or swap with the **Resend** node (`RESEND_API_KEY`).
3. **Lumi Backend API**: In n8n environment variables or workflow settings:
   - `LUMI_API_URL`: e.g. `http://127.0.0.1:8000` (or your deployed Lumi domain)
   - `LUMI_API_TOKEN`: User API token or Bearer secret for authentication.

---

## 3. Triggering the Automation

### Option A: Webhook Trigger (On-Demand or via Lumi App)
Trigger the scan dynamically by making a `POST` request to the n8n webhook URL:

```bash
curl -X POST http://localhost:5678/webhook/lumi-niche-radar \
  -H "Content-Type: application/json" \
  -d '{
    "profile_id": 1,
    "recipient_email": "creator@example.com",
    "niche_title": "AI & SaaS Growth",
    "keywords": ["ai automation", "growth hacking", "b2b saas"],
    "alert_threshold": 1.5
  }'
```

### Option B: Scheduled Run (Daily / Weekly Briefings)
Add an n8n **Schedule Trigger** (e.g., Every morning at 8:00 AM) connected to an HTTP Request node that fetches active preferences from Lumi:
```http
GET {{ $env.LUMI_API_URL }}/api/v1/intelligence/niche-preferences/active?profile_id=1
Authorization: Bearer <token>
```
The response returns the profile's active keywords and recipient email, passing them directly to the `Prepare Dynamic Search Queries & Parameters` node.

---

## 4. Lumi Backend Endpoints (Built & Tested)

The backend endpoints supporting this automation are live in `lumi/apps/intelligence/`:

### 1. Active Niche Preferences
* **Endpoint**: `GET /api/v1/intelligence/niche-preferences/active?profile_id=<id>`
* **Description**: Returns active niche title, keywords array, competitor handles, and notification email.
* **Response**:
```json
{
  "profile_id": 1,
  "email": "user@example.com",
  "niche_key": "b2b-saas:global",
  "title": "B2B SaaS Growth",
  "keywords": ["saas growth", "cold outreach", "ai marketing"],
  "handles": ["@sama", "@karpathy"],
  "is_active": true
}
```

### 2. Niche Report & Framework Ingestion
* **Endpoint**: `POST /api/v1/intelligence/niche-reports/ingest`
* **Description**: Ingests multi-platform winner posts, calculated metric snapshots, and frameworks with evidence references.
* **Payload**:
```json
{
  "profile_id": 1,
  "niche": "AI Automation",
  "query": "ai agents OR automation",
  "origin": "pipeline",
  "posts_analyzed": 40,
  "winner_count": 2,
  "peers_analyzed": 4,
  "posts": [
    {
      "platform_post_id": "123456789",
      "platform": "x",
      "author_handle": "automate_daily",
      "author_display_name": "Automate Daily",
      "caption": "How to build an AI agent in 10 minutes...",
      "url": "https://x.com/automate_daily/status/123456789",
      "published_at": "2026-11-01T12:00:00Z",
      "likes": 450,
      "comments": 38,
      "views": 18000,
      "format": "thread"
    }
  ],
  "frameworks": [
    {
      "name": "TUTORIAL: how_to_promise (x)",
      "description": "Step-by-step breakdown triggering curiosity and retention.",
      "lift": 2.5,
      "confidence": 0.9,
      "ordinal": 0,
      "payload": {
        "hook_type": "how_to_promise",
        "primary_framework": "tutorial",
        "cta_type": "like_bookmark"
      },
      "evidence_platform_post_ids": ["123456789"]
    }
  ]
}
```
* **Response**:
```json
{
  "ok": true,
  "report_id": 15,
  "frameworks_count": 1,
  "posts_saved": 1
}
```
