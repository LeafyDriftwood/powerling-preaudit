"""
Pillar 4 — Online Reputation data gathering.

Wires together three steps:
  1. YouTube API: find official channel + extract stats
  2. (optional) GPT validation: only if Step 1 finds no confident match
  3. Website footer scraper: find social media links from the company site
  4. GPT research: discover all reputation data, using Steps 1+3 as hints

Public API:
  gather_pillar4_facts(domain, company_name) -> dict
"""

import json
import os
import re
from typing import Optional
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup
from openai import OpenAI

openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _domain_host(domain: str) -> str:
    """Strip protocol and www — e.g. 'https://www.oxypharm.net' -> 'oxypharm.net'."""
    return re.sub(r"^https?://(www\.)?", "", domain).rstrip("/")


def _fetch_channel_external_links(channel_id: str) -> list:
    """
    Scrape a YouTube channel page and return external links from the Links section.
    YouTube encodes external links as redirect URLs: youtube.com/redirect?...&q=ENCODED_URL
    Returns a list of decoded URLs (youtube.com URLs excluded).
    """
    url = f"https://www.youtube.com/channel/{channel_id}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=12)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [warn] channel page fetch failed: {e}")
        return []

    text = resp.text.replace("\\u0026", "&").replace("\\u003d", "=")
    raw_qs = re.findall(r'[?&]q=(https?[^&"\'}\s\\]+)', text)
    seen = set()
    result = []
    for q in raw_qs:
        decoded = unquote(q)
        if "youtube.com" not in decoded and decoded not in seen:
            seen.add(decoded)
            result.append(decoded)
    return result


# ---------------------------------------------------------------------------
# Step 1 — YouTube API: search + domain validation
# ---------------------------------------------------------------------------

def _step1_youtube(domain: str, company_name: str) -> tuple:
    """
    Search YouTube for the company's official channel.

    Returns (youtube_data, uncertain_candidates):
      - youtube_data: dict with channel_url/subscribers/videos, or None if not found
      - uncertain_candidates: list of channel dicts that didn't pass domain validation
        (passed to Step 2 if youtube_data is None)
    """
    host = _domain_host(domain)

    try:
        search_resp = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "q": company_name,
                "type": "channel",
                "maxResults": 5,
                "key": YOUTUBE_API_KEY,
            },
            timeout=10,
        )
        search_resp.raise_for_status()
        channel_ids = [item["id"]["channelId"] for item in search_resp.json().get("items", [])]

        if not channel_ids:
            return None, []

        det_resp = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={
                "part": "snippet,statistics,brandingSettings",
                "id": ",".join(channel_ids),
                "key": YOUTUBE_API_KEY,
            },
            timeout=10,
        )
        det_resp.raise_for_status()
        channels = det_resp.json().get("items", [])
    except Exception as e:
        print(f"  [warn] YouTube API call failed: {e}")
        return None, []

    confident = []
    uncertain = []

    for ch in channels:
        snippet  = ch.get("snippet", {})
        stats    = ch.get("statistics", {})
        branding = ch.get("brandingSettings", {}).get("channel", {})

        description = snippet.get("description", "")
        keywords    = branding.get("keywords", "")

        domain_in_desc     = host.lower() in description.lower()
        domain_in_keywords = host.lower() in keywords.lower()

        external_links = _fetch_channel_external_links(ch["id"])
        domain_in_links = any(
            urlparse(link).netloc.removeprefix("www.").lower() == host.lower()
            for link in external_links
        )

        entry = {
            "id": ch["id"],
            "title": snippet.get("title", ""),
            "custom_url": snippet.get("customUrl", ""),
            "channel_url": f"https://www.youtube.com/channel/{ch['id']}",
            "country": snippet.get("country", ""),
            "subscribers": stats.get("subscriberCount", "hidden"),
            "videos": stats.get("videoCount", "?"),
            "views": stats.get("viewCount", "?"),
            "description": description,
            "keywords": keywords,
            "external_links": external_links,
        }

        if domain_in_desc or domain_in_keywords or domain_in_links:
            confident.append(entry)
        else:
            uncertain.append(entry)

    if confident:
        best = confident[0]
        return {
            "channel_url": best["channel_url"],
            "subscribers": best["subscribers"],
            "videos": best["videos"],
        }, []

    return None, uncertain


# ---------------------------------------------------------------------------
# Step 2 — GPT: validate ambiguous YouTube candidates
# ---------------------------------------------------------------------------

def _step2_gpt_channel_validation(
    domain: str,
    company_name: str,
    candidates: list,
) -> Optional[dict]:
    """
    Ask GPT to pick the correct YouTube channel from ambiguous candidates.
    If a match is found, fetches its stats from the API and returns youtube_data.
    Returns None if no confident match.
    """
    candidates_str = json.dumps([
        {
            "id": c["id"],
            "title": c["title"],
            "custom_url": c["custom_url"],
            "country": c["country"],
            "subscribers": c["subscribers"],
            "description": c["description"][:300],
        }
        for c in candidates
    ], indent=2, ensure_ascii=False)

    prompt = f"""
We are auditing {company_name} ({domain}).

The following YouTube channels were returned by a search.
Determine which one, if any, is the official channel for {company_name}.

Candidates:
{candidates_str}

Rules:
- Prefer channels whose description or linked website matches {domain}
- Prefer channels whose title/handle closely matches the company name
- If none are clearly a match, return null

Return JSON only:
{{
  "selected_channel_id": "UCxxxxx or null",
  "confidence": "high / medium / low / none",
  "reasoning": "one sentence"
}}
"""
    resp = openai_client.responses.create(
        model="gpt-5",
        tools=[{"type": "web_search"}],
        input=prompt,
    )
    usage = getattr(resp, "usage", None)
    if usage:
        print(
            f"[pillar4 step2 tokens] "
            f"input={getattr(usage, 'input_tokens', '?')}  "
            f"output={getattr(usage, 'output_tokens', '?')}  "
            f"total={getattr(usage, 'total_tokens', '?')}"
        )
    raw = resp.output_text
    clean = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    clean = re.sub(r"\s*```$", "", clean)
    try:
        result = json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', clean, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
            except Exception:
                return None
        else:
            return None

    channel_id = result.get("selected_channel_id")
    if not channel_id:
        return None

    # Fetch stats for the selected channel
    det_resp = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={
            "part": "statistics",
            "id": channel_id,
            "key": YOUTUBE_API_KEY,
        },
        timeout=10,
    )
    det_resp.raise_for_status()
    items = det_resp.json().get("items", [])
    if not items:
        return None

    stats = items[0].get("statistics", {})
    return {
        "channel_url": f"https://www.youtube.com/channel/{channel_id}",
        "subscribers": stats.get("subscriberCount", "hidden"),
        "videos": stats.get("videoCount", "?"),
    }


# ---------------------------------------------------------------------------
# Step 3 — Website footer scraper
# ---------------------------------------------------------------------------

def _step3_footer_scraper(domain: str) -> dict:
    """
    Scrape the company website footer for social media links.
    Returns a dict of {platform: url} for platforms found.
    """
    url = domain if domain.startswith("http") else f"https://{domain}"

    PLATFORM_PATTERNS = {
        "linkedin":  r"linkedin\.com/company/",
        "twitter":   r"twitter\.com/|x\.com/",
        "instagram": r"instagram\.com/",
        "facebook":  r"facebook\.com/",
        "youtube":   r"youtube\.com/",
    }

    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; PowerlingAudit/1.0)"}
        resp = requests.get(url, timeout=12, headers=headers, allow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"  [warn] footer scraper failed for {url}: {e}")
        return {}

    search_zones = []
    footer = soup.find("footer")
    if footer:
        search_zones.append(footer)
    search_zones.append(soup)

    found = {}
    for zone in search_zones:
        if len(found) == len(PLATFORM_PATTERNS):
            break
        for a in zone.find_all("a", href=True):
            href = a["href"]
            for platform, pattern in PLATFORM_PATTERNS.items():
                if platform not in found and re.search(pattern, href, re.IGNORECASE):
                    found[platform] = href

    return found


# ---------------------------------------------------------------------------
# Step 4 — GPT research: full reputation audit
# ---------------------------------------------------------------------------

def _step4_gpt_research(
    domain: str,
    company_name: str,
    youtube_data: Optional[dict],
    candidate_links: dict,
) -> Optional[dict]:
    """
    GPT-5 researches the full online reputation.

    youtube_data is pre-populated from the YouTube API so GPT copies it as-is.
    candidate_links (from the footer scraper) are hints — GPT also searches for
    any platforms not in the hints list.
    """
    # Build hints string (excluding youtube — handled via pre-populated JSON)
    hint_lines = [
        f"  - {platform}: {url}"
        for platform, url in candidate_links.items()
        if platform != "youtube"
    ]
    hints_str = "\n".join(hint_lines) if hint_lines else "  None found."

    # Pre-build YouTube JSON so GPT doesn't re-search
    if youtube_data:
        yt_json = json.dumps({
            "url": youtube_data.get("channel_url"),
            "subscribers": youtube_data.get("subscribers"),
            "videos": youtube_data.get("videos"),
            "last_active": None,
        })
    else:
        yt_json = json.dumps({"url": None, "subscribers": None, "videos": None, "last_active": None})

    prompt = f"""
You are auditing the online reputation of {company_name} ({domain}).

TASK A — Social media accounts.
Find the official account for each platform: LinkedIn, X/Twitter, Instagram, Facebook.
The links below are starting points found on the company website — use them as hints,
but if a link is missing, search for the account independently. If a link looks like
a regional or secondary account, find the main one instead.

Starting points:
{hints_str}

For each platform record: correct URL, follower count, last active date.

TASK B — Employer reviews.
Search in the company's primary language and English:
  - Glassdoor: URL to the company's Glassdoor page, rating (out of 5), number of reviews, % recommend to a friend, CEO approval %
  - Indeed: URL to the company's Indeed page, rating, number of reviews

Before accepting any profile on either platform, verify it belongs to {company_name} ({domain})
by checking that the profile's website field matches {domain} or the company's HQ location
matches what you already know about this company. If multiple profiles exist with similar names,
prefer the one whose website and location match. If you cannot verify a match, return null for
that platform's fields — do not return data for the wrong company.

TASK C — Customer reviews.
  - Trustpilot: URL to the company's Trustpilot page, score, total reviews

TASK D — Credibility assets.
Search for certifications, regulatory approvals, ISO norms, CE marks, biocide
authorizations, or industry awards. Include dates where available.

TASK E — Trade fair presence.
Search for industry trade shows or conferences where {company_name} exhibited, sponsored, or presented in the last 12 months. Only include events you can verify with a specific source URL. Include event name, location, dates, and source URL.

TASK F — Recent news.
Search for press releases, media coverage, or notable announcements in the last
18 months. Include source URL and date.

TASK G — Controversies.
Any known lawsuits, data breaches, or reputational issues in the last 3 years? Return each as an object with date (YYYY-MM-DD), title, and url. If none found, return an empty array.

TASK H — Overall sentiment.
Summarize as positive / neutral / negative with a one-sentence justification.

Return JSON only — no markdown fences. Use the YouTube value below exactly as provided.

For any field where you have useful context — such as sample size caveats, content observed
on the page, account activity notes, or anything that would help an auditor interpret the
data — add a "note" key to that object. Notes are optional and free-form; use your judgement.
Notes must be plain text — no markdown links or citations.

Numeric requirements: For all review count fields (glassdoor_reviews, indeed_reviews,
trustpilot_reviews), return exact integers or null. Do not include
commas, plus signs, "K"/"M" shorthand, or text like "around" or "approximately". If the
exact count is unavailable, return null.

{{
  "social_media": {{
    "linkedin":  {{"url": "...", "followers": "...", "last_active": "...", "note": "..."}},
    "twitter":   {{"url": "...", "followers": "...", "last_active": "..."}},
    "instagram": {{"url": "...", "followers": "...", "last_active": "..."}},
    "facebook":  {{"url": "...", "followers": "...", "last_active": "..."}},
    "youtube":   {yt_json}
  }},
  "glassdoor_url": null,
  "glassdoor_score": null,
  "glassdoor_reviews": null,
  "glassdoor_recommend": null,
  "glassdoor_ceo_approval": null,
  "glassdoor_note": null,
  "indeed_url": null,
  "indeed_score": null,
  "indeed_reviews": null,
  "indeed_note": null,
  "trustpilot_url": null,
  "trustpilot_score": null,
  "trustpilot_reviews": null,
  "credibility_assets": ["ISO 9001 certified", "CE mark Class IIa"],
  "trade_fair_presence": [
    {{"event": "MEDICA 2025", "location": "Düsseldorf, DE", "dates": "2025-11-17 to 2025-11-20"}}
  ],
  "recent_news": [
    {{"date": "2025-06-01", "title": "...", "url": "..."}}
  ],
  "controversies": [{{"date": "YYYY-MM-DD", "title": "...", "url": "..."}}],
  "overall_sentiment": "positive",
  "sentiment_justification": "..."
}}
"""
    resp = openai_client.responses.create(
        model="gpt-5",
        tools=[{"type": "web_search"}],
        input=prompt,
    )
    usage = getattr(resp, "usage", None)
    if usage:
        print(
            f"[pillar4 step4 tokens] "
            f"input={getattr(usage, 'input_tokens', '?')}  "
            f"output={getattr(usage, 'output_tokens', '?')}  "
            f"total={getattr(usage, 'total_tokens', '?')}"
        )

    raw = resp.output_text
    clean = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    clean = re.sub(r"\s*```$", "", clean)
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', clean, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def gather_pillar4_facts(domain: str, company_name: str) -> dict:
    """
    Run the full Pillar 4 gathering pipeline and return a reputation facts dict.

    Steps:
      1. YouTube API — search for official channel, validate by domain match
      2. GPT validation — only if Step 1 finds no confident match
      3. Website footer — scrape social media links as hints
      4. GPT research — full reputation audit using Steps 1+3 as context
    """
    # Step 1
    youtube_data, uncertain_candidates = _step1_youtube(domain, company_name)

    # Step 2 — only if Step 1 found no confident match
    if youtube_data is None and uncertain_candidates:
        youtube_data = _step2_gpt_channel_validation(
            domain, company_name, uncertain_candidates
        )

    # Step 3
    candidate_links = _step3_footer_scraper(domain)

    # Step 4
    result = _step4_gpt_research(domain, company_name, youtube_data, candidate_links)

    if result is None:
        return {}

    if not isinstance(result.get("controversies"), list):
        result["controversies"] = []

    return result
