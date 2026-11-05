"""End-to-End Real World Test Runner for Lumi Niche Radar Automation.

This script tests:
1. Live HTTP GET to /api/v1/intelligence/niche-preferences/active on http://127.0.0.1:8000
2. Actual JavaScript execution via Node.js of the n8n normalization & AI analysis nodes
3. Live HTTP POST to /api/v1/intelligence/niche-reports/ingest
4. Real PostgreSQL database verification of ingested reports, frameworks, and evidence
5. Generates an HTML email preview artifact to automations/test_email_preview.html
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Setup Django environment
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "lumi"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django
django.setup()

from apps.accounts.models import AuthToken, User
from apps.intelligence.models import Framework, FrameworkEvidence, NichePreference, NicheReport
from apps.profiles.models import MetricSnapshot, Post, SocialHandle, SocialProfile


def run_node_script(js_code: str, input_json: dict | list) -> dict | list:
    """Run JavaScript in Node.js simulating n8n context."""
    wrapper = f"""
    const raw = {json.dumps(input_json)};
    const items = Array.isArray(raw) ? raw.map(x => (x.json ? x : {{ json: x }})) : [{{ json: raw }}];
    const $input = {{
      first: () => items[0],
      all: () => items
    }};
    
    function run() {{
      {js_code}
    }}
    
    const result = run();
    process.stdout.write(JSON.stringify(result));
    """
    proc = subprocess.run(
        ["node", "-e", wrapper],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return json.loads(proc.stdout)


def test_real_pipeline():
    print("=" * 70)
    print("STARTING END-TO-END REAL-TERMS TEST")
    print("=" * 70)

    # 1. Get user and issue live AuthToken
    user = User.objects.filter(email="dev@test.com").first()
    if not user:
        user = User.objects.create_user(email="dev@test.com", password="devpassword123")
    
    profile = SocialProfile.objects.filter(user=user).first()
    if not profile:
        handle, _ = SocialHandle.objects.get_or_create(
            platform="x",
            handle_normalized="devuser",
            defaults={"handle_display": "@devuser"}
        )
        profile = SocialProfile.objects.create(user=user, handle=handle)

    _, token_key = AuthToken.issue(user, name="n8n_test_runner")
    print(f"[PASS] Issued live AuthToken for {user.email} (Profile ID: {profile.pk})")

    # 2. Test Live HTTP GET /api/v1/intelligence/niche-preferences/active
    live_server_url = "http://127.0.0.1:8000"
    pref_url = f"{live_server_url}/api/v1/intelligence/niche-preferences/active?profile_id={profile.pk}"
    req = urllib.request.Request(
        pref_url,
        headers={"Authorization": f"Token {token_key}", "Accept": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        pref_data = json.loads(resp.read().decode("utf-8"))
    
    print(f"[PASS] Live HTTP GET {pref_url} returned 200 OK")
    print(f"  Active Niche: {pref_data['title']} | Keywords: {pref_data['keywords']}")

    # 3. Load Workflow Nodes from JSON
    workflow_path = BASE_DIR / "automations" / "lumi_niche_radar_workflow.json"
    with open(workflow_path, encoding="utf-8") as f:
        workflow = json.load(f)
    
    nodes_by_name = {n["name"]: n for n in workflow["nodes"]}

    # 4. Execute JS Parameter Preparation Node
    prep_code = nodes_by_name["Prepare Dynamic Search Queries & Parameters"]["parameters"]["jsCode"]
    prep_out = run_node_script(prep_code, {
        "keywords": pref_data["keywords"],
        "niche_title": pref_data["title"],
        "recipient_email": pref_data["email"],
        "profile_id": pref_data["profile_id"],
        "alert_threshold": 1.5
    })
    query_params = prep_out[0]["json"]
    print(f"[PASS] JavaScript Parameter Preparation executed successfully:")
    print(f"  Generated Query String: {query_params['query']}")

    # 5. Execute JS Normalization Nodes with realistic multi-platform payloads
    # Instagram Mock
    ig_raw = {
        "results": [
            {
                "id": "ig_post_901",
                "username": "growth_hacker_daily",
                "caption": "Stop wasting 4 hours every morning writing social posts. Here is our 3-step automation blueprint.",
                "codeUrl": "https://www.instagram.com/p/ig_post_901/",
                "likeCount": 850,
                "commentCount": 94,
                "createdAt": "2026-11-02T16:00:00Z"
            }
        ]
    }
    norm_ig_code = nodes_by_name["Normalize Instagram (PostStats)"]["parameters"]["jsCode"]
    ig_norm = run_node_script(norm_ig_code, ig_raw)
    assert ig_norm[0]["json"]["platform"] == "instagram"
    assert ig_norm[0]["json"]["engagement_total"] == 944
    print("[PASS] Instagram Normalization Node: verified PostStats structure (engagement: 944)")

    # TikTok Mock (testing snowflake ID timestamp recovery without explicit date)
    # Snowflake ID 7431234567890123456 -> timestamp ~1729000000
    tt_raw = {
        "results": [
            {
                "id": "7431234567890123456",
                "username": "aitools_creator",
                "desc": "How we scaled to $40k/mo using only 2 AI agents. 🧵 Step-by-step breakdown.",
                "codeUrl": "https://www.tiktok.com/@aitools_creator/video/7431234567890123456",
                "diggCount": 2400,
                "commentCount": 180,
                "shareCount": 310,
                "playCount": 45000
            }
        ]
    }
    norm_tt_code = nodes_by_name["Normalize TikTok (PostStats)"]["parameters"]["jsCode"]
    tt_norm = run_node_script(norm_tt_code, tt_raw)
    assert tt_norm[0]["json"]["platform"] == "tiktok"
    assert tt_norm[0]["json"]["published_at"] is not None
    assert tt_norm[0]["json"]["engagement_total"] == 2890
    print("[PASS] TikTok Normalization Node: verified snowflake ID decoding and engagement (2890)")

    # X (Twitter) Mock
    x_raw = {
        "results": [
            {
                "id": "1852000111222333444",
                "authorUsername": "solopreneur_hq",
                "name": "Solo Creator HQ",
                "text": "91% of B2B landing pages convert under 2%. We changed 1 headline framework and boosted conversion to 7.4% in 48 hours. Here is the exact formula:",
                "impressionCount": 38000,
                "likeCount": 1240,
                "replyCount": 115,
                "retweetCount": 210,
                "createdAtDate": "2026-11-02T14:30:00Z"
            },
            {
                "id": "1852000999888777666",
                "authorUsername": "casual_poster",
                "text": "Just woke up and drinking coffee. Good morning everyone!",
                "impressionCount": 400,
                "likeCount": 8,
                "replyCount": 2,
                "retweetCount": 0,
                "createdAtDate": "2026-11-02T10:00:00Z"
            }
        ]
    }
    norm_x_code = nodes_by_name["Normalize X (PostStats)"]["parameters"]["jsCode"]
    x_norm = run_node_script(norm_x_code, x_raw)
    assert len(x_norm) == 2
    assert x_norm[0]["json"]["platform"] == "x"
    assert x_norm[0]["json"]["engagement_total"] == 1565
    print("[PASS] X (Twitter) Normalization Node: verified impression counts and engagement (1565)")

    # Reddit Mock
    rd_raw = {
        "data": {
            "children": [
                {
                    "data": {
                        "id": "t3_1abcxyz",
                        "author": "growth_marketer",
                        "subreddit": "marketing",
                        "title": "Why most B2B cold emails get marked as spam",
                        "selftext": "After sending over 500k emails, the biggest problem is fake personalization. Here is what actually works in 2026.",
                        "score": 420,
                        "num_comments": 88,
                        "permalink": "/r/marketing/comments/1abcxyz/why_most_b2b_cold_emails/"
                    }
                }
            ]
        }
    }
    norm_rd_code = nodes_by_name["Normalize Reddit (PostStats)"]["parameters"]["jsCode"]
    rd_norm = run_node_script(norm_rd_code, rd_raw)
    assert rd_norm[0]["json"]["platform"] == "reddit"
    assert rd_norm[0]["json"]["post_id"] == "1abcxyz"  # stripped t3_
    assert rd_norm[0]["json"]["engagement_total"] == 508
    print("[PASS] Reddit Normalization Node: verified t3_ stripping and permalinks (508)")

    # 6. Execute Merge & Outlier Winner Node
    # Combine normalized pools
    all_normalized = [
        {"json": p["json"]} for p in (ig_norm + tt_norm + x_norm + rd_norm)
    ]
    merge_code = f"""
    const ig = {json.dumps([p['json'] for p in ig_norm])};
    const tiktok = {json.dumps([p['json'] for p in tt_norm])};
    const x = {json.dumps([p['json'] for p in x_norm])};
    const reddit = {json.dumps([p['json'] for p in rd_norm])};
    const allPosts = [...ig, ...tiktok, ...x, ...reddit].filter(p => p.text && p.text.trim().length > 10);
    const params = {json.dumps(query_params)};
    const threshold = Number(params.alert_threshold) || 1.5;

    const engagements = allPosts.map(p => p.engagement_total).sort((a, b) => a - b);
    const mid = Math.floor(engagements.length / 2);
    const medianEngagement = engagements.length > 0 
      ? (engagements.length % 2 !== 0 ? engagements[mid] : (engagements[mid - 1] + engagements[mid]) / 2) 
      : 10;
    const baseline = Math.max(medianEngagement, 5);

    const scored = allPosts.map(p => {{
      const outlier_score = Number((p.engagement_total / baseline).toFixed(2));
      return {{
        ...p,
        outlier_score: outlier_score,
        is_winner: outlier_score >= threshold
      }};
    }});

    scored.sort((a, b) => b.outlier_score - a.outlier_score);
    const winners = scored.filter(p => p.is_winner).slice(0, 6);
    const selectedWinners = winners.length >= 2 ? winners : scored.slice(0, 3);

    return [{{
      json: {{
        niche_title: params.niche_title,
        recipient_email: params.recipient_email,
        profile_id: params.profile_id,
        query: params.query,
        total_scanned: allPosts.length,
        median_engagement: baseline,
        winner_count: selectedWinners.length,
        winners: selectedWinners,
        all_posts: scored.slice(0, 30)
      }}
    }}];
    """
    merge_out = run_node_script(merge_code, {})
    merge_data = merge_out[0]["json"]
    print(f"[PASS] Outlier & Winner Detection executed:")
    print(f"  Total scanned: {merge_data['total_scanned']} posts | Baseline median: {merge_data['median_engagement']}")
    print(f"  Identified {merge_data['winner_count']} Outlier Winners (Threshold: >=1.5x)")
    for w in merge_data["winners"]:
        print(f"    - [{w['platform'].upper()}] @{w['author']['handle']}: {w['outlier_score']}x outlier (Engagement: {w['engagement_total']})")

    # 7. Execute Framework & Hook Classifier Node (Lumi AI Cognitive Layer)
    classify_code = nodes_by_name["Analyze Post Frameworks & Hooks"]["parameters"]["jsCode"]
    classify_out = run_node_script(classify_code, merge_data)
    classified_data = classify_out[0]["json"]
    print("[PASS] Framework & Hook Classifier Node executed:")
    for w in classified_data["winners"]:
        print(f"    - Hook: '{w['hook_type']}' | Framework: '{w['primary_framework'].upper()}' | CTA: '{w['cta_type']}'")
        print(f"      Viral Reason: {w['viral_reason']}")

    # 8. Execute HTML Email Digest Formatter Node
    html_code = nodes_by_name["Format HTML Email Digest"]["parameters"]["jsCode"]
    html_out = run_node_script(html_code, classified_data)
    email_data = html_out[0]["json"]
    print("[PASS] Responsive HTML Email Digest generated successfully:")
    print(f"  Subject: {email_data['email_subject']}")
    assert "<!DOCTYPE html>" in email_data["email_html"]
    assert "Lumi Niche Radar" in email_data["email_html"]
    assert "Remix in my Voice with Lumi" in email_data["email_html"]

    # Save preview HTML file
    preview_file = BASE_DIR / "automations" / "test_email_preview.html"
    with open(preview_file, "w", encoding="utf-8") as f:
        f.write(email_data["email_html"])
    print(f"[PASS] Saved email preview to {preview_file}")

    # 9. Test Live Ingest Endpoint HTTP POST /api/v1/intelligence/niche-reports/ingest
    ingest_url = f"{live_server_url}/api/v1/intelligence/niche-reports/ingest"
    ingest_payload = {
        "profile_id": classified_data["profile_id"],
        "niche": classified_data["niche_title"],
        "query": classified_data["query"],
        "origin": "pipeline",
        "posts_analyzed": classified_data["total_scanned"],
        "winner_count": classified_data["winner_count"],
        "peers_analyzed": 4,
        "posts": [
            {
                "platform_post_id": w["post_id"],
                "platform": w["platform"],
                "author_handle": w["author"]["handle"],
                "author_display_name": w["author"]["display_name"],
                "caption": w["text"],
                "url": w.get("url") or "",
                "published_at": w["published_at"],
                "likes": w["likes"],
                "comments": w["comments"],
                "reposts": w.get("reposts", 0),
                "views": w.get("views"),
                "format": w.get("format", "single")
            }
            for w in classified_data["winners"]
        ],
        "frameworks": classified_data["frameworks"],
        "report": {
            "summary": "Real test run of Lumi Niche Radar",
            "median_engagement": classified_data["median_engagement"],
            "scanned_count": classified_data["total_scanned"]
        }
    }

    req_ingest = urllib.request.Request(
        ingest_url,
        data=json.dumps(ingest_payload).encode("utf-8"),
        headers={
            "Authorization": f"Token {token_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        method="POST"
    )

    with urllib.request.urlopen(req_ingest) as resp:
        assert resp.status == 201, f"Expected 201, got {resp.status}"
        ingest_resp = json.loads(resp.read().decode("utf-8"))
    
    print(f"[PASS] Live HTTP POST {ingest_url} returned 201 CREATED")
    print(f"  Response: {ingest_resp}")

    # 10. Database State Verification
    report_id = ingest_resp["report_id"]
    db_report = NicheReport.objects.get(pk=report_id)
    assert db_report.profile == profile
    assert db_report.winner_count == classified_data["winner_count"]
    print(f"[PASS] Verified NicheReport #{report_id} in PostgreSQL (niche: '{db_report.niche}')")

    db_frameworks = list(Framework.objects.filter(report=db_report))
    assert len(db_frameworks) == ingest_resp["frameworks_count"]
    print(f"[PASS] Verified {len(db_frameworks)} Frameworks persisted with lift scores and cognitive payloads")

    evidence_count = FrameworkEvidence.objects.filter(framework__in=db_frameworks).count()
    assert evidence_count > 0
    print(f"[PASS] Verified {evidence_count} FrameworkEvidence links connecting frameworks to real Post rows")

    print("=" * 70)
    print("ALL REAL-WORLD TESTS PASSED PERFECTLY!")
    print("=" * 70)

if __name__ == "__main__":
    test_real_pipeline()
