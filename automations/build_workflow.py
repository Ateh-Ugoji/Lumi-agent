import json
import uuid

def generate_n8n_workflow():
    nodes = []
    connections = {}

    # 1. Webhook Trigger
    webhook_node = {
        "parameters": {
            "httpMethod": "POST",
            "path": "lumi-niche-radar",
            "responseMode": "onReceived",
            "options": {}
        },
        "id": "11111111-1111-4111-8111-111111111111",
        "name": "Webhook - Trigger Lumi Niche Radar",
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "position": [440, 100],
        "webhookId": "lumi-niche-radar-hook"
    }
    nodes.append(webhook_node)

    # 2. Manual Trigger
    manual_node = {
        "parameters": {},
        "id": "22222222-2222-4222-8222-222222222222",
        "name": "When clicking ‘Test workflow’",
        "type": "n8n-nodes-base.manualTrigger",
        "typeVersion": 1,
        "position": [440, 280]
    }
    nodes.append(manual_node)

    # 3. Parameter Preparation Node
    prepare_code = """const input = $input.first()?.json || {};
const body = input.body || input;

// Extract dynamic inputs with fallbacks
const keywords = Array.isArray(body.keywords) && body.keywords.length > 0 
  ? body.keywords 
  : (typeof body.keywords === 'string' ? body.keywords.split(',').map(s => s.trim()) : ['ai marketing', 'automation', 'growth']);

const niche_title = body.niche_title || 'AI Automation & Marketing';
const recipient_email = body.recipient_email || body.email || 'creator@example.com';
const alert_threshold = Number(body.alert_threshold) || 1.5;
const profile_id = Number(body.profile_id) || 1;

// Build search query: (keyword1) OR (keyword2)
const queryString = keywords.length > 1 
  ? keywords.map(k => `"${k}"`).join(' OR ') 
  : (keywords[0] || 'marketing');

return [{
  json: {
    query: queryString,
    keywords: keywords,
    niche_title: niche_title,
    recipient_email: recipient_email,
    alert_threshold: alert_threshold,
    profile_id: profile_id,
    timestamp: new Date().toISOString()
  }
}];"""

    prepare_node = {
        "parameters": {
            "jsCode": prepare_code
        },
        "id": "33333333-3333-4333-8333-333333333333",
        "name": "Prepare Dynamic Search Queries & Parameters",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [720, 180]
    }
    nodes.append(prepare_node)

    # 4. HTTP Request Nodes (Xpoz)
    cred_xpoz = {
        "httpTemplatedCustomAuth": {
            "id": "xZtZMjq5kdG0EPFb",
            "name": "Xpoz Access Key (Christian F)"
        }
    }

    ig_http = {
        "parameters": {
            "url": "https://api.xpoz.ai/api/data/instagram/posts/live",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpTemplatedCustomAuth",
            "sendQuery": True,
            "queryParameters": {
                "parameters": [
                    {
                        "name": "q",
                        "value": "={{ $('Prepare Dynamic Search Queries & Parameters').item.json.query }}"
                    },
                    {
                        "name": "fields",
                        "value": "id,username,caption,codeUrl,likeCount,commentCount,createdAt"
                    }
                ]
            },
            "options": {
                "timeout": 120000
            }
        },
        "id": "d5e120b8-7fb2-424d-98e6-30e30b27de5c",
        "name": "Xpoz - Instagram Posts",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.5,
        "position": [1080, -220],
        "credentials": cred_xpoz
    }
    nodes.append(ig_http)

    tiktok_http = {
        "parameters": {
            "url": "https://api.xpoz.ai/api/data/tiktok/posts/live",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpTemplatedCustomAuth",
            "sendQuery": True,
            "queryParameters": {
                "parameters": [
                    {
                        "name": "q",
                        "value": "={{ $('Prepare Dynamic Search Queries & Parameters').item.json.query }}"
                    }
                ]
            },
            "options": {
                "timeout": 120000
            }
        },
        "id": "89420ed7-5f9b-4040-a657-1471514fca65",
        "name": "Xpoz - TikTok Posts",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.5,
        "position": [1080, -40],
        "credentials": cred_xpoz
    }
    nodes.append(tiktok_http)

    x_http = {
        "parameters": {
            "url": "https://api.xpoz.ai/api/data/twitter/posts/live",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpTemplatedCustomAuth",
            "sendQuery": True,
            "queryParameters": {
                "parameters": [
                    {
                        "name": "q",
                        "value": "={{ $('Prepare Dynamic Search Queries & Parameters').item.json.query }}"
                    }
                ]
            },
            "options": {
                "timeout": 120000
            }
        },
        "id": "45ca4ccf-389a-48d0-ab40-9f794b7704ab",
        "name": "Xpoz - X Posts",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.5,
        "position": [1080, 140],
        "credentials": cred_xpoz
    }
    nodes.append(x_http)

    reddit_http = {
        "parameters": {
            "url": "https://api.xpoz.ai/api/data/reddit/posts/live",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpTemplatedCustomAuth",
            "sendQuery": True,
            "queryParameters": {
                "parameters": [
                    {
                        "name": "q",
                        "value": "={{ $('Prepare Dynamic Search Queries & Parameters').item.json.query }}"
                    }
                ]
            },
            "options": {
                "timeout": 120000
            }
        },
        "id": "b313d8d6-19d4-41c2-b89b-f032c42999ff",
        "name": "Xpoz - Reddit Posts",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.5,
        "position": [1080, 320],
        "credentials": cred_xpoz
    }
    nodes.append(reddit_http)

    # 5. Normalization Nodes
    norm_ig_code = """const posts = $input.all().flatMap(i => i.json.results || i.json.data || [i.json]);

return posts.slice(0, 15).map(item => {
  const id = item.id ? String(item.id) : ('ig_' + Math.random().toString(36).substring(7));
  const autor = item.username || item.author || 'instagram_creator';
  const texto = item.caption || item.text || '';
  const enlace = item.codeUrl || item.url || (id ? `https://www.instagram.com/p/${id}/` : null);
  const likes = Number(item.likeCount ?? item.likes ?? 0);
  const comments = Number(item.commentCount ?? item.comments ?? 0);
  const engagement_total = likes + comments;

  let published_at = item.createdAt ? new Date(item.createdAt).toISOString() : new Date().toISOString();
  let age_hours = Math.max(1, Math.round((Date.now() - new Date(published_at).getTime()) / 3600000));

  return {
    json: {
      post_id: id,
      platform: 'instagram',
      author: {
        handle: autor,
        display_name: item.authorName || autor,
        avatar_url: item.profileImageUrl || ''
      },
      text: texto,
      url: enlace,
      format: 'multi_image',
      published_at: published_at,
      age_hours: age_hours,
      views: item.viewCount ? Number(item.viewCount) : null,
      likes: likes,
      comments: comments,
      reposts: 0,
      engagement_total: engagement_total,
      engagement_rate: item.viewCount ? Number(((engagement_total / Number(item.viewCount)) * 100).toFixed(2)) : null
    }
  };
});"""

    norm_ig_node = {
        "parameters": {"jsCode": norm_ig_code},
        "id": "a3c0fe70-d997-4802-aef7-e2c210ab3abb",
        "name": "Normalize Instagram (PostStats)",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [1360, -220]
    }
    nodes.append(norm_ig_node)

    norm_tiktok_code = """const inputItems = $input.all();
const rawList = inputItems.flatMap(i => i.json.results || i.json.data || i.json.posts || [i.json]);

function formatearFecha(val, id) {
  if (val) {
    if (typeof val === 'number') {
      const ms = val > 1e11 ? val : val * 1000;
      return new Date(ms).toISOString();
    }
    const parsed = new Date(val);
    if (!isNaN(parsed.getTime())) return parsed.toISOString();
  }
  try {
    if (id) {
      const idBig = BigInt(String(id).replace(/\\D/g, ''));
      const timestampSec = Number(idBig >> 32n);
      if (timestampSec > 1400000000 && timestampSec < 2200000000) {
        return new Date(timestampSec * 1000).toISOString();
      }
    }
  } catch (e) {}
  return new Date().toISOString();
}

return rawList.slice(0, 15).map(raw => {
  const item = raw.data || raw.post || raw.video || raw;
  const id = item.id || item.video_id || item.aweme_id || ('tt_' + Math.random().toString(36).substring(7));
  const autor = item.username || item.author?.uniqueId || item.author?.username || 'tiktok_creator';
  const texto = item.caption || item.desc || item.description || item.title || '';
  const enlace = item.codeUrl || item.webVideoUrl || item.url || (id && autor ? `https://www.tiktok.com/@${autor}/video/${id}` : null);
  
  const likes = Number(item.likeCount ?? item.diggCount ?? item.likes ?? 0);
  const comments = Number(item.commentCount ?? item.comments ?? 0);
  const reposts = Number(item.shareCount ?? item.reposts ?? 0);
  const views = Number(item.playCount ?? item.viewCount ?? item.views ?? 0);
  const engagement_total = likes + comments + reposts;

  const published_at = formatearFecha(item.createdAt || item.createTime || item.publishTime, id);
  const age_hours = Math.max(1, Math.round((Date.now() - new Date(published_at).getTime()) / 3600000));

  return {
    json: {
      post_id: String(id),
      platform: 'tiktok',
      author: {
        handle: autor,
        display_name: item.author?.nickname || autor,
        avatar_url: item.author?.avatarLarger || item.author?.avatarThumb || ''
      },
      text: texto,
      url: enlace,
      format: 'video',
      published_at: published_at,
      age_hours: age_hours,
      views: views > 0 ? views : null,
      likes: likes,
      comments: comments,
      reposts: reposts,
      engagement_total: engagement_total,
      engagement_rate: views > 0 ? Number(((engagement_total / views) * 100).toFixed(2)) : null
    }
  };
});"""

    norm_tiktok_node = {
        "parameters": {"jsCode": norm_tiktok_code},
        "id": "568bbe56-855a-4fe7-8ef4-6ba47f0b3697",
        "name": "Normalize TikTok (PostStats)",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [1360, -40]
    }
    nodes.append(norm_tiktok_node)

    norm_x_code = """const inputItems = $input.all();
const rawList = inputItems.flatMap(i => i.json.results || i.json.data || [i.json]);

function formatearFecha(fechaStr) {
  if (!fechaStr) return new Date().toISOString();
  const d = new Date(fechaStr);
  return !isNaN(d.getTime()) ? d.toISOString() : new Date().toISOString();
}

return rawList.slice(0, 15).map(raw => {
  const item = raw.data || raw;
  const id = item.id ? String(item.id) : ('tw_' + Math.random().toString(36).substring(7));
  const autor = item.authorUsername || item.username || item.author || 'x_user';
  const texto = item.text || item.full_text || item.caption || '';
  const enlace = autor && id ? `https://x.com/${autor}/status/${id}` : (id ? `https://x.com/i/status/${id}` : null);
  
  const views = Number(item.impressionCount || item.views || 0);
  const likes = Number(item.likeCount ?? item.favoriteCount ?? item.likes ?? 0);
  const comments = Number(item.replyCount ?? item.commentCount ?? item.comments ?? 0);
  const reposts = Number(item.retweetCount ?? item.repostCount ?? item.shares ?? 0);
  const engagement_total = likes + comments + reposts;

  const published_at = formatearFecha(item.createdAtDate || item.createdAt || item.created_at);
  const age_hours = Math.max(1, Math.round((Date.now() - new Date(published_at).getTime()) / 3600000));

  return {
    json: {
      post_id: id,
      platform: 'x',
      author: {
        handle: autor,
        display_name: item.authorName || item.name || autor,
        avatar_url: item.profileImageUrl || ''
      },
      text: texto,
      url: enlace,
      format: texto.length > 280 ? 'long_form' : 'single',
      published_at: published_at,
      age_hours: age_hours,
      views: views > 0 ? views : null,
      likes: likes,
      comments: comments,
      reposts: reposts,
      engagement_total: engagement_total,
      engagement_rate: views > 0 ? Number(((engagement_total / views) * 100).toFixed(2)) : null
    }
  };
});"""

    norm_x_node = {
        "parameters": {"jsCode": norm_x_code},
        "id": "31ddbd6d-74aa-4ead-9015-5d1d73d42ef5",
        "name": "Normalize X (PostStats)",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [1360, 140]
    }
    nodes.append(norm_x_node)

    norm_reddit_code = """const inputItems = $input.all();
const rawList = inputItems.flatMap(i => i.json.results || i.json.data?.children || i.json.data || i.json.posts || [i.json]);

function formatearFecha(val) {
  if (!val) return new Date().toISOString();
  if (typeof val === 'number') {
    const ms = val > 1e11 ? val : val * 1000;
    return new Date(ms).toISOString();
  }
  const d = new Date(val);
  return !isNaN(d.getTime()) ? d.toISOString() : new Date().toISOString();
}

return rawList.slice(0, 15).map(raw => {
  const item = raw.data || raw.post || raw;
  const id = item.id ? String(item.id).replace(/^t3_/, '') : ('rd_' + Math.random().toString(36).substring(7));
  const autor = item.authorUsername || item.author || 'reddit_user';
  const subreddit = item.subreddit || item.subredditName || 'reddit';
  
  const texto = (item.title ? item.title + (item.selftext || item.text ? '\\n\\n' + (item.selftext || item.text) : '') : '') || item.text || '';
  const permalink = item.permalink || item.url || item.codeUrl;
  const enlace = permalink ? (permalink.startsWith('http') ? permalink : `https://www.reddit.com${permalink}`) : `https://redd.it/${id}`;
  
  const likes = Number(item.score ?? item.ups ?? item.likeCount ?? 0);
  const comments = Number(item.numComments ?? item.num_comments ?? item.comments ?? 0);
  const engagement_total = likes + comments;

  const published_at = formatearFecha(item.createdAtDate || item.createdAt || item.createdUtc || item.created_utc);
  const age_hours = Math.max(1, Math.round((Date.now() - new Date(published_at).getTime()) / 3600000));

  return {
    json: {
      post_id: id,
      platform: 'reddit',
      subreddit: subreddit,
      author: {
        handle: autor,
        display_name: `u/${autor}`,
        avatar_url: ''
      },
      text: texto,
      url: enlace,
      format: 'long_form',
      published_at: published_at,
      age_hours: age_hours,
      views: null,
      likes: likes,
      comments: comments,
      reposts: 0,
      engagement_total: engagement_total,
      engagement_rate: null
    }
  };
});"""

    norm_reddit_node = {
        "parameters": {"jsCode": norm_reddit_code},
        "id": "786603c5-145e-4a23-942a-32b8a19b854d",
        "name": "Normalize Reddit (PostStats)",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [1360, 320]
    }
    nodes.append(norm_reddit_node)

    # 6. Merge & Rank Outlier Winners Node
    merge_code = """const ig = $('Normalize Instagram (PostStats)').all().map(i => i.json);
const tiktok = $('Normalize TikTok (PostStats)').all().map(i => i.json);
const x = $('Normalize X (PostStats)').all().map(i => i.json);
const reddit = $('Normalize Reddit (PostStats)').all().map(i => i.json);

const allPosts = [...ig, ...tiktok, ...x, ...reddit].filter(p => p.text && p.text.trim().length > 10);
const params = $('Prepare Dynamic Search Queries & Parameters').first().json;
const threshold = Number(params.alert_threshold) || 1.5;

// Compute median engagement
const engagements = allPosts.map(p => p.engagement_total).sort((a, b) => a - b);
const mid = Math.floor(engagements.length / 2);
const medianEngagement = engagements.length > 0 
  ? (engagements.length % 2 !== 0 ? engagements[mid] : (engagements[mid - 1] + engagements[mid]) / 2) 
  : 10;
const baseline = Math.max(medianEngagement, 5);

// Score outliers
const scored = allPosts.map(p => {
  const outlier_score = Number((p.engagement_total / baseline).toFixed(2));
  return {
    ...p,
    outlier_score: outlier_score,
    is_winner: outlier_score >= threshold
  };
});

// Sort by outlier score descending
scored.sort((a, b) => b.outlier_score - a.outlier_score);

const winners = scored.filter(p => p.is_winner).slice(0, 6);
// If not enough winners hit threshold, take top 3 performers
const selectedWinners = winners.length >= 2 ? winners : scored.slice(0, 3);

return [{
  json: {
    niche_title: params.niche_title,
    recipient_email: params.recipient_email,
    profile_id: params.profile_id,
    query: params.query,
    total_scanned: allPosts.length,
    median_engagement: baseline,
    winner_count: selectedWinners.length,
    winners: selectedWinners,
    all_posts: scored.slice(0, 30)
  }
}];"""

    merge_node = {
        "parameters": {"jsCode": merge_code},
        "id": "44444444-4444-4444-8444-444444444444",
        "name": "Merge & Rank Outlier Winners",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [1680, 60]
    }
    nodes.append(merge_node)

    # 7. Framework & Hook Classifier Node (Lumi AI Cognitive Layer)
    classify_code = """const data = $input.first().json;
const winners = data.winners || [];

function detectHookType(text) {
  const lower = text.toLowerCase();
  if (/^stop\\b|never|don't|wrong|mistake|myth/i.test(lower)) return 'contrarian';
  if (/\\d+%|\\$\\d+|\\d+ (ways|tools|lessons|steps|days|hours|tips)/i.test(lower)) return 'stat_shock';
  if (/why|how to|here is how|secret|nobody talks about/i.test(lower)) return 'curiosity_gap';
  if (/tired of|struggling with|if you spend|wasting time/i.test(lower)) return 'pain_callout';
  if (/how (i|we) (made|built|grew|scaled|reached)/i.test(lower)) return 'result_claim';
  if (/\\?$/.test(text.split('\\n')[0].trim())) return 'question';
  return 'observation';
}

function detectFramework(text) {
  const lower = text.toLowerCase();
  if (lower.includes('problem') || lower.includes('instead') || lower.includes('solution') || lower.includes('here is why')) return 'pas';
  if (lower.includes('1.') || lower.includes('2.') || lower.includes('🧵') || lower.includes('- ') || lower.includes('• ')) return 'listicle';
  if (lower.includes('years ago') || lower.includes('when i started') || lower.includes('fast forward')) return 'story_arc';
  if (lower.includes('attention') || lower.includes('link') || lower.includes('drop a comment')) return 'aida';
  if (lower.includes('step 1') || lower.includes('how to')) return 'tutorial';
  return 'hot_take';
}

function detectCTA(text) {
  const lower = text.toLowerCase();
  if (lower.includes('comment') || lower.includes('reply with')) return 'reply_keyword';
  if (lower.includes('bookmark') || lower.includes('save this')) return 'like_bookmark';
  if (lower.includes('repost') || lower.includes('retweet')) return 'repost';
  if (lower.includes('link in') || lower.includes('check the link') || lower.includes('http')) return 'link';
  if (lower.includes('follow')) return 'follow';
  return 'none';
}

const enrichedWinners = winners.map((post, idx) => {
  const firstLine = (post.text || '').split('\\n')[0].replace(/^[#\\s]+/, '').trim();
  const hook_type = detectHookType(firstLine);
  const framework = detectFramework(post.text || '');
  const cta = detectCTA(post.text || '');

  let viral_reason = 'Strong curiosity gap paired with actionable clarity.';
  if (hook_type === 'contrarian') viral_reason = 'Challenges mainstream consensus, triggering engagement and debate.';
  else if (hook_type === 'stat_shock') viral_reason = 'Specific quantifiable metrics provide immediate high authority and proof.';
  else if (hook_type === 'pain_callout') viral_reason = 'Deeply resonates with the target audience daily friction point.';
  else if (hook_type === 'result_claim') viral_reason = 'Outcome-first hook demonstrates proven social proof.';

  let remix_angle = `Hook the reader with a ${hook_type} opening, agitate the core problem in your niche, and deliver your unique methodology as the solution.`;

  return {
    ...post,
    hook_text: firstLine.substring(0, 140),
    hook_type: hook_type,
    primary_framework: framework,
    cta_type: cta,
    viral_reason: viral_reason,
    remix_angle: remix_angle,
    ordinal: idx
  };
});

// Build frameworks payload for Lumi Ingest API
const frameworksPayload = enrichedWinners.map((w, idx) => ({
  name: `${w.primary_framework.toUpperCase()}: ${w.hook_type} (${w.platform})`,
  description: w.viral_reason,
  lift: w.outlier_score,
  confidence: 0.88,
  ordinal: idx,
  payload: {
    hook_type: w.hook_type,
    primary_framework: w.primary_framework,
    cta_type: w.cta_type,
    remix_angle: w.remix_angle,
    viral_reason: w.viral_reason
  },
  evidence_platform_post_ids: [w.post_id]
}));

return [{
  json: {
    ...data,
    winners: enrichedWinners,
    frameworks: frameworksPayload
  }
}];"""

    classify_node = {
        "parameters": {"jsCode": classify_code},
        "id": "55555555-5555-4555-8555-555555555555",
        "name": "Analyze Post Frameworks & Hooks",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [1940, 60]
    }
    nodes.append(classify_node)

    # 8. HTML Email Digest Formatter
    html_code = """const data = $input.first().json;
const winners = data.winners || [];
const niche = data.niche_title || 'Your Niche';

const brandColors = {
  x: '#1d9bf0',
  tiktok: '#ff0050',
  instagram: '#e1306c',
  reddit: '#ff4500'
};

const cardsHtml = winners.map(w => {
  const color = brandColors[w.platform] || '#6366f1';
  const viewsDisplay = w.views ? `<span>👁️ <strong>${Number(w.views).toLocaleString()}</strong> views</span>` : '';
  const likesDisplay = `<span>❤️ <strong>${Number(w.likes).toLocaleString()}</strong></span>`;
  const commentsDisplay = `<span>💬 <strong>${Number(w.comments).toLocaleString()}</strong></span>`;

  return `
  <div style="background: #14161b; border: 1px solid #272a34; border-radius: 10px; padding: 20px; margin-bottom: 20px;">
    <!-- Badges Row -->
    <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap;">
      <span style="background: ${color}22; color: ${color}; font-size: 11px; font-weight: 700; text-transform: uppercase; padding: 3px 8px; border-radius: 4px; border: 1px solid ${color}44;">
        ${w.platform}
      </span>
      <span style="background: #6366f122; color: #a5b4fc; font-size: 11px; font-weight: 600; text-transform: uppercase; padding: 3px 8px; border-radius: 4px; border: 1px solid #6366f144;">
        ${w.primary_framework.toUpperCase()} FRAMEWORK
      </span>
      <span style="background: #eab30822; color: #fde047; font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 4px; border: 1px solid #eab30844;">
        ⚡ ${w.hook_type.replace('_', ' ')}
      </span>
      <span style="background: #22c55e22; color: #4ade80; font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 4px; margin-left: auto;">
        🔥 ${w.outlier_score}x Outlier
      </span>
    </div>

    <!-- Author & Hook Text -->
    <div style="font-size: 12px; color: #9ca3af; margin-bottom: 8px;">
      By <strong>@${w.author.handle}</strong> on ${w.platform}
    </div>
    <div style="font-size: 15px; font-weight: 600; color: #f9fafb; line-height: 1.5; margin-bottom: 14px; background: #0c0d10; padding: 12px; border-radius: 8px; border-left: 3px solid ${color};">
      "${w.hook_text}"
    </div>

    <!-- Metrics Bar -->
    <div style="display: flex; gap: 16px; font-size: 12px; color: #9ca3af; padding-bottom: 12px; border-bottom: 1px solid #22252e; margin-bottom: 14px;">
      ${viewsDisplay}
      ${likesDisplay}
      ${commentsDisplay}
    </div>

    <!-- Why it Worked Callout -->
    <div style="background: #181b22; padding: 10px 14px; border-radius: 6px; font-size: 12px; color: #d1d5db; line-height: 1.4; margin-bottom: 14px;">
      <strong style="color: #a5b4fc;">Why it worked:</strong> ${w.viral_reason}<br/>
      <strong style="color: #4ade80; display: inline-block; margin-top: 4px;">Remix Idea:</strong> ${w.remix_angle}
    </div>

    <!-- Action Buttons -->
    <div style="display: flex; gap: 10px;">
      ${w.url ? `<a href="${w.url}" target="_blank" style="color: #cbd5e1; background: #232733; text-decoration: none; font-size: 12px; font-weight: 500; padding: 8px 14px; border-radius: 6px; border: 1px solid #333846; display: inline-block;">View Original Post ↗</a>` : ''}
      <a href="http://localhost:3010/chat?remix_post_id=${w.post_id}&platform=${w.platform}" target="_blank" style="background: #6366f1; color: #ffffff; text-decoration: none; font-size: 12px; font-weight: 600; padding: 8px 16px; border-radius: 6px; display: inline-block;">Remix in my Voice with Lumi ✍️</a>
    </div>
  </div>
  `;
}).join('\\n');

const fullHtml = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Lumi Niche Radar</title>
</head>
<body style="margin: 0; padding: 24px; background: #07080a; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #e5e7eb;">
  <div style="max-width: 620px; margin: 0 auto; background: #0c0e12; border: 1px solid #1f222b; border-radius: 12px; overflow: hidden; padding: 28px;">
    
    <!-- Top Header -->
    <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #1f232e; padding-bottom: 20px; margin-bottom: 24px;">
      <div>
        <h1 style="font-size: 22px; font-weight: 700; color: #ffffff; margin: 0 0 6px 0;">⚡ Lumi Niche Radar</h1>
        <div style="font-size: 13px; color: #9ca3af;">High-performing frameworks in <span style="color: #6366f1; font-weight: 600;">${niche}</span></div>
      </div>
      <span style="background: #6366f122; color: #818cf8; font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 20px; border: 1px solid #6366f155;">
        ${winners.length} Winners Detected
      </span>
    </div>

    <!-- Scanned Overview Pill -->
    <div style="background: #12141a; border: 1px solid #20242f; border-radius: 8px; padding: 12px 16px; font-size: 12px; color: #94a3b8; margin-bottom: 24px; display: flex; justify-content: space-between;">
      <span>Scanned <strong>${data.total_scanned} posts</strong> across X, TikTok, IG & Reddit</span>
      <span>Threshold: <strong>${data.median_engagement} avg / ≥1.5x</strong></span>
    </div>

    <!-- Cards List -->
    ${cardsHtml}

    <!-- Footer -->
    <div style="border-top: 1px solid #1f232e; padding-top: 20px; margin-top: 30px; text-align: center; font-size: 11px; color: #64748b;">
      <p style="margin: 0 0 8px;">Generated autonomously by Lumi Intelligence for profile #${data.profile_id}.</p>
      <p style="margin: 0;"><a href="http://localhost:3010/settings" style="color: #6366f1; text-decoration: none;">Manage Niche Keywords & Preferences</a></p>
    </div>

  </div>
</body>
</html>
`;

return [{
  json: {
    ...data,
    email_subject: `⚡ Lumi Niche Radar: ${winners.length} Top Frameworks in ${niche}`,
    email_html: fullHtml
  }
}];"""

    html_node = {
        "parameters": {"jsCode": html_code},
        "id": "66666666-6666-4666-8666-666666666666",
        "name": "Format HTML Email Digest",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [2200, 60]
    }
    nodes.append(html_node)

    # 9. Send Email Node
    email_node = {
        "parameters": {
            "fromEmail": "notifications@lumiai.com",
            "toEmail": "={{ $json.recipient_email }}",
            "subject": "={{ $json.email_subject }}",
            "html": "={{ $json.email_html }}",
            "options": {}
        },
        "id": "77777777-7777-4777-8777-777777777777",
        "name": "Send Email Alert",
        "type": "n8n-nodes-base.emailSend",
        "typeVersion": 2.1,
        "position": [2460, -40]
    }
    nodes.append(email_node)

    # 10. Sync to Lumi Ingestion API Node
    sync_code = {
        "parameters": {
            "method": "POST",
            "url": "={{ ($env.LUMI_API_URL || 'http://127.0.0.1:8000') + '/api/v1/intelligence/niche-reports/ingest' }}",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {
                        "name": "Content-Type",
                        "value": "application/json"
                    },
                    {
                        "name": "Authorization",
                        "value": "={{ 'Bearer ' + ($env.LUMI_API_TOKEN || '') }}"
                    }
                ]
            },
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={\n  \"profile_id\": {{ $json.profile_id }},\n  \"niche\": \"{{ $json.niche_title }}\",\n  \"query\": \"{{ $json.query }}\",\n  \"origin\": \"pipeline\",\n  \"posts_analyzed\": {{ $json.total_scanned }},\n  \"winner_count\": {{ $json.winner_count }},\n  \"peers_analyzed\": 4,\n  \"posts\": {{ JSON.stringify($json.winners.map(w => ({\n    platform_post_id: w.post_id,\n    platform: w.platform,\n    author_handle: w.author.handle,\n    author_display_name: w.author.display_name,\n    caption: w.text,\n    url: w.url || '',\n    published_at: w.published_at,\n    likes: w.likes,\n    comments: w.comments,\n    reposts: w.reposts,\n    views: w.views,\n    format: w.format\n  }))) }},\n  \"frameworks\": {{ JSON.stringify($json.frameworks) }},\n  \"report\": {\n    \"summary\": \"Niche discovery scan across 4 networks\",\n    \"median_engagement\": {{ $json.median_engagement }},\n    \"scanned_count\": {{ $json.total_scanned }}\n  }\n}",
            "options": {
                "timeout": 30000
            }
        },
        "id": "88888888-8888-4888-8888-888888888888",
        "name": "Sync to Lumi Ingestion API",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.5,
        "position": [2460, 160]
    }
    nodes.append(sync_code)

    # Connections
    connections = {
        "Webhook - Trigger Lumi Niche Radar": {
            "main": [[{"node": "Prepare Dynamic Search Queries & Parameters", "type": "main", "index": 0}]]
        },
        "When clicking ‘Test workflow’": {
            "main": [[{"node": "Prepare Dynamic Search Queries & Parameters", "type": "main", "index": 0}]]
        },
        "Prepare Dynamic Search Queries & Parameters": {
            "main": [[
                {"node": "Xpoz - Instagram Posts", "type": "main", "index": 0},
                {"node": "Xpoz - TikTok Posts", "type": "main", "index": 0},
                {"node": "Xpoz - X Posts", "type": "main", "index": 0},
                {"node": "Xpoz - Reddit Posts", "type": "main", "index": 0}
            ]]
        },
        "Xpoz - Instagram Posts": {
            "main": [[{"node": "Normalize Instagram (PostStats)", "type": "main", "index": 0}]]
        },
        "Xpoz - TikTok Posts": {
            "main": [[{"node": "Normalize TikTok (PostStats)", "type": "main", "index": 0}]]
        },
        "Xpoz - X Posts": {
            "main": [[{"node": "Normalize X (PostStats)", "type": "main", "index": 0}]]
        },
        "Xpoz - Reddit Posts": {
            "main": [[{"node": "Normalize Reddit (PostStats)", "type": "main", "index": 0}]]
        },
        "Normalize Instagram (PostStats)": {
            "main": [[{"node": "Merge & Rank Outlier Winners", "type": "main", "index": 0}]]
        },
        "Normalize TikTok (PostStats)": {
            "main": [[{"node": "Merge & Rank Outlier Winners", "type": "main", "index": 0}]]
        },
        "Normalize X (PostStats)": {
            "main": [[{"node": "Merge & Rank Outlier Winners", "type": "main", "index": 0}]]
        },
        "Normalize Reddit (PostStats)": {
            "main": [[{"node": "Merge & Rank Outlier Winners", "type": "main", "index": 0}]]
        },
        "Merge & Rank Outlier Winners": {
            "main": [[{"node": "Analyze Post Frameworks & Hooks", "type": "main", "index": 0}]]
        },
        "Analyze Post Frameworks & Hooks": {
            "main": [[{"node": "Format HTML Email Digest", "type": "main", "index": 0}]]
        },
        "Format HTML Email Digest": {
            "main": [[
                {"node": "Send Email Alert", "type": "main", "index": 0},
                {"node": "Sync to Lumi Ingestion API", "type": "main", "index": 0}
            ]]
        }
    }

    workflow = {
        "name": "Lumi - Niche Radar & Email Alerts",
        "nodes": nodes,
        "connections": connections,
        "pinData": {},
        "meta": {
            "templateCredsSetupCompleted": True,
            "instanceId": "lumi-niche-radar-v1"
        }
    }

    with open("automations/lumi_niche_radar_workflow.json", "w", encoding="utf-8") as f:
        json.dump(workflow, f, indent=2, ensure_ascii=False)
    print("Workflow successfully generated and saved to automations/lumi_niche_radar_workflow.json")

if __name__ == "__main__":
    generate_n8n_workflow()
