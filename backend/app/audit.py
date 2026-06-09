"""
Audit pipeline for Powerling Pre-Audit system.

Pipeline phases (run_audit):
  Phase 0:  Playwright crawler - client site (pillar1_gather.py)
            Extracts hreflang tags, locale URLs, language selector, cookie banner.
            Followed by GPT-5 mixed language check across locale pages.
  Phase 0b: Website health data (website_health.py)
            Google PSI (mobile + desktop), DataForSEO OnPage crawl, homepage checks.
  Phase 1:  Client data gathering - 2 independent gpt-5 calls
            Turn 1: Globalization - crawler facts injected as authoritative; GPT
                    fills geographic_presence, required_languages, traffic only.
            Turn 2: Accessibility & Compliance - independent call; Turn 1 geographic
                    context injected so GPT can infer applicable regulations.
  Phase 1b: Online reputation (pillar4_gather.py)
            YouTube API + GPT-5 web search.
  Phase 2:  Competitor data - one Playwright crawl + one gpt-5 call per competitor.
  Phase 3:  build_facts_pack - merges all data, computes LCR deterministically.
  Phase 4:  generate_ui_content - GPT-5 Responses API, no web search.
            Produces executive_summary, per-pillar headlines/findings/recommendations,
            competitive_landscape, top_recommendations.

API strategy:
- gpt-5 (Responses API, tools=[web_search]): all web search calls. JSON enforced
  via prompt + _parse_json() with json_repair fallback.
- gpt-5 (Responses API, no tools): generate_ui_content only.
"""

import json
import os
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from openai import OpenAI

try:
    from app.log_ctx import _ctx, plog
except ImportError:
    from log_ctx import _ctx, plog

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


# Helper functions for audit pipeline
def _strip_citations(obj):
    """Recursively strip GPT web-search markdown links ([text](url)) from all string values."""
    if isinstance(obj, str):
        return re.sub(r'\s*\(\[[^\]]*\]\([^)]*\)\)', '', obj).strip()
    if isinstance(obj, dict):
        return {k: _strip_citations(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_citations(i) for i in obj]
    return obj


def _normalize_lang_codes(data: dict) -> dict:
    """Uppercase available_languages entries that look like ISO codes and drop full names."""
    if not isinstance(data, dict):
        return data
    for field in ("available_languages", "required_languages"):
        langs = data.get(field)
        # drop entries that aren't ISO code formats (incudes codes or variant codes)
        if isinstance(langs, list):
            data[field] = [
                l.upper() for l in langs
                if isinstance(l, str) and re.match(r'^[a-zA-Z]{2}(-[a-zA-Z]{2,4})?$', l)
            ]
    return data


def _parse_review_count(val: str) -> "int | None":
    """Parse review count strings like '50,000+', '50k', '1.2M' to int."""
    upper = val.strip().upper()
    mult = 1_000_000 if upper.endswith("M") else 1_000 if upper.endswith("K") else 1
    digits = re.sub(r"[^\d.]", "", upper)
    return int(float(digits) * mult) if digits else None


def _parse_json(text: str, label: str = "") -> dict:
    """Parse JSON from a model response, stripping markdown fences if present."""

    # clean json by removing wrapper markdown fences and any surrounding whitespace
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    try:
        return _normalize_lang_codes(_strip_citations(json.loads(text)))
    except json.JSONDecodeError as e:
        tag = f"[{label}] " if label else ""
        plog(f"{tag}JSON parse error: {e}")
        plog(f"{tag}Response length: {len(text)} chars")
        plog(f"{tag}Last 300 chars: {text[-300:]!r}")

        # try json repair for issues in json format
        try:
            from json_repair import repair_json
            repaired = repair_json(text)
            result = json.loads(repaired)
            plog(f"{tag}Recovered via json_repair.")
            return _normalize_lang_codes(_strip_citations(result))
        except Exception:
            pass
        # try to extract a JSON object from within the text (handles preamble/postamble)
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            plog(f"{tag}Attempting extraction from embedded JSON block...")
            return _normalize_lang_codes(_strip_citations(json.loads(match.group())))
        raise


def gather_all_client_data(url: str, company_name: str, crawler_facts: dict = None) -> tuple:
    """
    Gather client Pillar 1 and Pillar 3 data with two independent GPT-5 calls.

    Turn 1 (Globalization): crawler_facts injected as authoritative for structural fields
    (available_languages, hreflang, locale_urls). GPT researches geographic_presence,
    required_languages, and traffic only.

    Turn 2 (Accessibility): independent call with no Turn 1 history, to avoid the
    6000 TPM ceiling on large sites. Cookie banner from Playwright injected as authoritative.

    Returns (pillar1_data, pillar3_data).
    """
    # ------------------------------------------------------------------
    # Turn 1: Globalization
    # ------------------------------------------------------------------

    crawler_ran = bool(crawler_facts and crawler_facts.get("crawler_ran"))

    if crawler_ran:
        # Format mixed-language issues for injection into the gpt prompt
        ml_issues = crawler_facts.get("mixed_language_issues", [])
        if ml_issues:
            detail_parts = []
            for iss in ml_issues:
                locale = iss.get("locale", "?")
                page_url = iss.get("page_url", "?")
                hits = iss.get("language_hits", [])
                if hits:
                    hit_fragments = []
                    for hit in hits:
                        lang = hit.get("language", "?")
                        strings = hit.get("marker_strings_found", [])
                        hit_fragments.append(f"{lang}: {strings}")
                    detail_parts.append(f"{locale} page ({page_url}): " + " | ".join(hit_fragments))
            ml_detail = "; ".join(detail_parts)
        else:
            ml_detail = "None detected (all locale pages checked)"

        locale_urls_json = json.dumps(crawler_facts.get("locale_urls", {}), ensure_ascii=False)
        hreflang_tags_count = len(crawler_facts.get("hreflang_tags", []))
        plog(f"[audit]   hreflang tags count: {hreflang_tags_count}")
        target_langs_json = json.dumps(crawler_facts.get("target_languages", []), ensure_ascii=False)

        x_default_status = (
            f"Yes, pointing to {crawler_facts.get('hreflang_x_default_url')}"
            if crawler_facts.get("hreflang_x_default_present")
            else ("No x-default tag found" if crawler_facts.get("hreflang_present") else "No hreflang tags at all")
        )

        turn1_prompt = f"""
You are auditing the website {url} for globalization.

The following structural facts have been confirmed by direct website analysis.
Use these EXACT values in your JSON response for the listed fields - do not re-research them:
  available_languages: {crawler_facts['available_languages']}
  language_selector_type: "{crawler_facts['language_selector_type']}"
    locale_urls: {locale_urls_json}
  hreflang_present: {crawler_facts['hreflang_present']} ({hreflang_tags_count} tags detected)
  hreflang_x_default: {x_default_status}
    pages_checked: {crawler_facts.get('pages_checked', 0)}
    target_languages_checked_for_mixing: {target_langs_json}
  mixed_language_ux_issues: {ml_detail}
  translation_plugin: {crawler_facts.get('translation_plugin') or 'none'}

STEP 1 - Research the company's geographic presence:
Search for where {company_name} operates, sells, or has customers. Look for:
- Number of countries and specific regions (Europe, APAC, MENA, Americas, CEE, etc.)
- International distributor network, subsidiaries, or office locations
- Press releases, About pages, or annual reports mentioning global reach or country count

STEP 2 - Search for any separate regional websites or market-specific domains beyond {url}.
Only count distinct apex domains or country-code TLDs (e.g. company.co.uk, company.de) that serve a specific market independently. Do NOT include subdirectory locales (e.g. company.com/uk/).
For each found, note: domain name, primary language served, target market.

STEP 3 - Derive Required Languages (RL) from the geographic footprint found in Step 1:
RL definition: identify the top 5-8 countries by traffic share using any traffic tool (Semrush, Similarweb, etc.).
Map each country to its dominant official or commercial language.
RL = the distinct languages needed to serve those markets natively — no more, no fewer.
required_languages must reflect the company's actual significant customer base,
not what is already on the website and not an assumption about what a company "should" have.
Prefer traffic data. If no traffic tool has data for this domain, fall back to the geographic
footprint from Step 1 — use the company's key markets and regions to infer which languages
are needed. Do not return an empty array.

STEP 4 - Available Languages (AL) validation rule:
AL counts ONLY languages where the FULL user experience is available:
navigation, product catalog, cart, checkout, and customer service all in that language.
Do NOT count: partial translations, footer-only language switches, blog-only languages,
or third-party subdomains not part of the main site.
The crawler has already confirmed the available languages above. Use those exact values.

STEP 5 - Note translation quality on the website:
Any observations on machine vs. professional translation, inconsistencies, or untranslated sections.
If translation_plugin is set (e.g. "gtranslate", "weglot", "google-translate"), flag that available languages are served via a machine translation overlay — this is a localization quality concern worth noting.

STEP 6 - Traffic data:
Search Semrush (semrush.com/website/[domain]/overview/) for monthly organic traffic and top traffic countries.
If Semrush has data, return it as a clean string like "9.1M (Semrush, Mar 2026)".
If Semrush has no data for this domain, set estimated_monthly_traffic to null and top_traffic_countries to [].
Do not include URLs, markdown links, or citation text in the value.

Return ONLY a valid JSON object with no markdown fences.
Only return the fields below — do NOT include available_languages, language_selector_type,
locale_urls, hreflang_present, pages_checked, or target_languages as those are already known:
IMPORTANT: The JSON below shows field names and value types ONLY. Do NOT copy these example values — replace every value with your actual research findings above.
{{
  "geographic_presence": "[your actual finding: regions and country count]",
  "required_languages": ["XX", "XX"],
  "mixed_language_ux_issues": "[brief plain-text summary, or 'None detected']",
  "translation_quality_notes": "[your actual finding]",
  "lcr_notes": "[your actual finding]",
  "estimated_monthly_traffic": null,
  "top_traffic_countries": ["XX", "XX", "XX"],
  "regional_sites": [{{"domain": "[domain]", "language": "XX", "market": "[market]", "note": "[note]"}}]
}}
"""
    else:
        turn1_prompt = f"""
You are auditing the website {url} for globalization.

STEP 1 - Research the company's geographic presence FIRST before looking at the website:
Search for where this company operates, sells, or has customers. Look for:
- Number of countries and specific regions (Europe, APAC, MENA, Americas, CEE, etc.)
- International distributor network, subsidiaries, or office locations
- Press releases, About pages, or annual reports mentioning global reach or country count

STEP 2 - Derive Required Languages (RL) from the geographic footprint found in Step 1:
RL definition: identify the top 5-8 countries by traffic share using any traffic tool (Semrush, Similarweb, etc.).
Map each country to its dominant official or commercial language.
RL = the distinct languages needed to serve those markets natively — no more, no fewer.
required_languages must reflect the company's actual significant customer base,
not what is already on the website and not an assumption about what a company "should" have.
Prefer traffic data. If no traffic tool has data for this domain, fall back to the geographic
footprint from Step 1 — use the company's key markets and regions to infer which languages
are needed. Do not return an empty array.

STEP 3 - Determine Available Languages (AL) from the website:
AL counts ONLY languages where the FULL user experience is available:
navigation, product catalog, cart, checkout, and customer service all in that language.
Count official brand-operated ccTLD or regional domains (e.g. company.de, company.co.jp) as available languages — these are part of the brand's digital footprint even if hosted separately.
Do NOT count: partial translations, footer-only language switches, blog-only languages,
or third-party sites not operated by the company itself.
Note the type of language selector (dropdown, flags, country selector, subdomain, path prefix, etc.).
Also check: are hreflang tags present on the website? If yes, is there an x-default hreflang tag?

STEP 4 - Check for mixed-language UX issues:
For example: untranslated CTAs appearing on non-matching locale pages, navigation in the wrong language,
or inconsistent locale switching. Be specific if found.

STEP 5 - Note translation quality on the website:
Any observations on machine vs. professional translation, inconsistencies, or untranslated sections.

STEP 6 - Search for any separate regional websites or market-specific domains beyond {url}.
Only count distinct apex domains or country-code TLDs (e.g. company.co.uk, company.de) that serve a specific market independently. Do NOT include subdirectory locales (e.g. company.com/uk/).
For each found, note: domain name, primary language, target market.

STEP 7 - Traffic data:
Search Semrush (semrush.com/website/[domain]/overview/) for monthly organic traffic and top traffic countries.
If Semrush has data, return it as a clean string like "9.1M (Semrush, Mar 2026)".
If Semrush has no data for this domain, set estimated_monthly_traffic to null and top_traffic_countries to [].
Do not include URLs, markdown links, or citation text in the value.

Return ONLY a valid JSON object with no markdown fences.
IMPORTANT: The JSON below shows field names and value types ONLY. Do NOT copy these example values — replace every value with your actual research findings above.
hreflang_present and hreflang_x_default_present must be JSON booleans (true or false), never null or a string.
For available_languages and required_languages, use ISO language codes (e.g. EN, FR, ZH-CN, PT-BR). Never use full language names.
{{
  "available_languages": ["XX", "XX"],
  "language_selector_type": "[your actual finding]",
  "geographic_presence": "[your actual finding: regions and country count]",
  "required_languages": ["XX", "XX"],
  "hreflang_present": null,
  "hreflang_x_default_present": null,
  "mixed_language_ux_issues": "[brief plain-text summary, or 'None detected']",
  "mixed_language_affected_locales_count": 0,
  "translation_quality_notes": "[your actual finding]",
  "lcr_notes": "[your actual finding]",
  "estimated_monthly_traffic": null,
  "top_traffic_countries": ["XX", "XX", "XX"],
  "regional_sites": []
}}
"""

    resp1 = client.responses.create(
        model="gpt-5",
        tools=[{"type": "web_search"}],
        input=turn1_prompt,
    )
    usage = getattr(resp1, "usage", None)
    if usage:
        plog(f"[audit] turn1 tokens: input={getattr(usage, 'input_tokens', '?')} output={getattr(usage, 'output_tokens', '?')}")
    p1_text = resp1.output_text
    pillar1_data = _parse_json(p1_text, label="Turn1-Globalization")
    plog("[audit]   Turn 1 (Globalization) complete.")

    # ------------------------------------------------------------------
    # Turn 2: Accessibility & Compliance
    # Context injected: URL, company name, available languages + locale URLs from
    # the crawler so GPT can infer the applicable regulatory framework (GDPR, RGAA,
    # ADA, etc.) without needing the full Turn 1 conversation history.
    # ------------------------------------------------------------------
    available_languages = (
        crawler_facts.get("available_languages") if crawler_facts
        else pillar1_data.get("available_languages", [])
    ) or []
    locale_urls = (
        crawler_facts.get("locale_urls") if crawler_facts
        else pillar1_data.get("locale_urls", {})
    ) or {}
    locale_urls_json = json.dumps(locale_urls, ensure_ascii=False)

    # insert cookie banner info deterministically if detected, otherwise allow it to look for one
    cookie_banner_detected = crawler_facts.get("cookie_banner_detected") if crawler_facts else None
    cookie_provider = crawler_facts.get("cookie_provider") if crawler_facts else None
    if cookie_banner_detected is not None:
        cookie_context = (
            f"Yes (provider: {cookie_provider})" if cookie_provider
            else ("Yes (provider unknown)" if cookie_banner_detected else "No — not detected on page load")
        )
        cookie_instruction = (
            f"AUTHORITATIVE FACT: Direct browser analysis confirmed cookie consent banner: {cookie_context}. "
            f"Use this exact value for has_cookie_banner and cookie_provider. Do NOT re-research it."
        )
    else:
        cookie_instruction = "Search the website for a cookie consent banner."

    geographic_presence = pillar1_data.get("geographic_presence", "unknown")
    top_traffic_countries = pillar1_data.get("top_traffic_countries", [])

    turn2_prompt = f"""
You are auditing the website {url} ({company_name}) for accessibility and legal compliance.

Context from direct site analysis:
- Geographic presence: {geographic_presence}
- Top traffic countries: {top_traffic_countries}
- Available languages: {available_languages}
- Locale URLs: {locale_urls_json}
- Cookie consent: {cookie_instruction}

Use the geographic presence and top traffic countries above to determine which regulatory frameworks apply (e.g. ADA for US, GDPR for EU, EN 301 549 for EU public sector). Do not assume — base this on the evidence above.

Search the website and answer the following:
1. Does the website have an accessibility statement? (yes/no, and URL if yes)
2. Does the website have a cookie banner/consent mechanism? (yes/no, and provider name if identifiable from the banner UI or page source)
3. Does the website have a privacy policy? (yes/no)
4. Does the website have a terms of service / terms of use? (yes/no)
5. Are there any obvious WCAG accessibility issues? List only issues you can specifically verify on the site.
6. What country/region is the company primarily based in?
7. Has the company faced any accessibility-related lawsuits or complaints? Search public records.
8. Does the website have a publicly accessible sitemap?
9. What WCAG accessibility level does the website claim or appear to target? (e.g., "WCAG 2.1 AA", "WCAG 2.0 A", "RGAA v4.1 partial", "undeclared"). Check the footer, accessibility statement, and legal notices.
10. How is alt text coverage across the site? Use one of: consistent / partial / missing / unknown, and describe your actual finding with specific examples from the site.
11. How is keyboard navigation? Is there a visible "skip to content" or "skip to main" link? Any keyboard traps in navigation menus or carousels?
12. Does the website use any third-party forms or scripts that introduce trackers before consent is given? Name the specific tools found if any.
13. Are there any PDFs or downloadable documents? If so, do they appear to be text-based (selectable text, screen-reader friendly) or image-based scans?

Return ONLY a valid JSON object with no markdown fences.
IMPORTANT: The JSON below shows field names and value types ONLY. Do NOT copy these example values — replace every value with your actual research findings above.
{{
  "has_accessibility_statement": false,
  "accessibility_statement_url": null,
  "has_cookie_banner": false,
  "cookie_provider": null,
  "has_privacy_policy": false,
  "has_terms_of_service": false,
  "has_sitemap": false,
  "wcag_issues": ["[specific issue found]"],
  "wcag_level_claimed": "[your actual finding or 'undeclared']",
  "alt_text_coverage": "[your actual finding]",
  "keyboard_navigation": "[your actual finding]",
  "third_party_forms": "[your actual finding or null]",
  "pdf_accessibility": "[your actual finding or null]",
  "primary_region": "[actual country]",
  "applicable_regulations": ["[applicable regulation based on region]"],
  "accessibility_lawsuits": []
}}
"""

    resp2 = client.responses.create(
        model="gpt-5",
        tools=[{"type": "web_search"}],
        input=turn2_prompt,
    )
    usage = getattr(resp2, "usage", None)
    if usage:
        plog(f"[audit] turn2 tokens: input={getattr(usage, 'input_tokens', '?')} output={getattr(usage, 'output_tokens', '?')}")
    p3_text = resp2.output_text
    pillar3_data = _parse_json(p3_text, label="Turn2-Accessibility")
    plog("[audit]   Turn 2 (Accessibility) complete.")

    return pillar1_data, pillar3_data


def gather_competitor_benchmark_data(url: str, crawler_available_languages: list = None) -> dict:
    """
    Gather all benchmark-relevant data for a single competitor in one search call.
    Returns structured data used to populate all three pillar benchmark tables.

    crawler_available_languages: if provided (from Playwright crawler), injected as authoritative
    so GPT does not re-detect languages.
    """
    if crawler_available_languages is not None:
        lang_note = (
            f"AUTHORITATIVE FACT: Direct website analysis has confirmed this competitor's website "
            f"serves the following languages (full UX): {crawler_available_languages}. "
            f"Use these EXACT values for available_languages. Do NOT re-research them.\n\n"
        )
    else:
        lang_note = ""

    _lang_question_suffix = (
        " (ALREADY CONFIRMED ABOVE - use those values)"
        if crawler_available_languages is not None
        else (
            " Count official brand-operated ccTLD domains (e.g. company.fr, company.de, company.co.jp)"
            " as separate available languages — these are part of the brand's digital footprint"
            " even if hosted on a different domain."
        )
    )
    comp_prompt = f"""
Research the website {url} to gather competitive benchmark data. Search online for accurate, current information.

{lang_note}Find the following, with actual numbers wherever possible:

GLOBALIZATION:
1. What languages are available on the website? Only count full UX languages (not partial translations).{_lang_question_suffix}
2. Search for the company's geographic presence (countries, regions, key markets). Based on that footprint, estimate how many languages would justify a full translated UX — counting only languages where there is a substantial customer segment, not every language in every country of operation. Return this as required_languages_count (integer).
3. Brief description of global reach (number of countries, key regions).
4. Search Semrush (semrush.com/website/[domain]/overview/) for monthly organic traffic. Return a clean string like "9.1M (Semrush, Mar 2026)". If Semrush has no data for this domain, return null.

ACCESSIBILITY & COMPLIANCE:
5. Accessibility statement: yes/no
6. Any notable accessibility issues publicly reported.
7. What WCAG level does the site claim or appear to target? (e.g., "WCAG 2.1 AA", "undeclared")
8. Alt text coverage quality: consistent / partial / missing / unknown
9. Keyboard navigation quality: brief description, or "unknown"

ONLINE REPUTATION:
12. Brief factual description of their brand positioning based on what you find online.
13. Digital engagement level: High / Medium / Low (based on social following + review volume).
14. LinkedIn follower count - search directly for their LinkedIn company page by name.
15. Total social media reach estimate across all platforms.
16. Review score (Trustpilot) if available. Return as a numeric float (e.g. 4.3) or null.
17. Overall online sentiment (positive / neutral / negative).

Return ONLY a valid JSON object with no markdown fences.
IMPORTANT: The JSON below shows field names and value types ONLY. Do NOT copy these example values — replace every value with your actual research findings above.
For available_languages, use ISO language codes (e.g. EN, FR, ZH-CN, PT-BR). Never use full language names.
{{
  "company_name": "[actual company name]",
  "available_languages": ["XX", "XX"],
  "required_languages_count": 0,
  "global_reach": "[your actual finding]",
  "estimated_monthly_traffic": null,
  "has_accessibility_statement": false,
  "wcag_level_claimed": "[your actual finding or 'undeclared']",
  "alt_text_coverage": "[your actual finding]",
  "keyboard_navigation": "[your actual finding]",
  "wcag_issues_noted": [],
  "brand_recognition": "[1-2 sentence description]",
  "digital_engagement": "[High / Medium / Low]",
  "linkedin_followers": "[actual number or 'unknown']",
  "social_media_reach": "[your actual finding or 'unknown']",
  "review_score": null,
  "overall_sentiment": "[positive / neutral / negative]"
}}
"""

    response = client.responses.create(
        model="gpt-5",
        tools=[{"type": "web_search"}],
        input=comp_prompt,
    )
    usage = getattr(response, "usage", None)
    if usage:
        plog(f"[audit] competitor tokens: input={getattr(usage, 'input_tokens', '?')} output={getattr(usage, 'output_tokens', '?')}")
    return _parse_json(response.output_text)


# ---------------------------------------------------------------------------
# Step 2: Compute deterministic metrics
# ---------------------------------------------------------------------------

def compute_lcr(available_languages: list, required_languages: list) -> float:
    """Calculate Language Coverage Rate: LCR = (AL / RL) * 100."""
    if not required_languages:
        return 0.0
    return round(len(set(available_languages) & set(required_languages)) / len(required_languages) * 100, 1)


def compute_lcr_tier(lcr: float) -> str:
    """Return Powerling LCR tier label."""
    if lcr >= 100:
        return "Full Coverage"
    elif lcr >= 76:
        return "Strong Coverage"
    elif lcr >= 51:
        return "Partial Coverage"
    else:
        return "Limited Coverage"


# ---------------------------------------------------------------------------
# Step 3: Build Facts Pack
# ---------------------------------------------------------------------------

def build_facts_pack(
    url: str,
    company_name: str,
    competitors: list,
    pillar1: dict,
    pillar3: dict,
    pillar4: dict,
    competitor_facts: list,
    pillar2: dict = None,
) -> dict:
    lcr_available_langs = pillar1.get("available_languages", [])
    lcr_required_langs = pillar1.get("required_languages", [])
    lcr = compute_lcr(lcr_available_langs, lcr_required_langs)
    lcr_tier = compute_lcr_tier(lcr)

    # Compute LCR and tier for each competitor
    for cf in competitor_facts:
        comp_required = int(cf.get("required_languages_count") or 0) or len(cf.get("required_languages", []))
        comp_available = len(cf.get("available_languages", []))
        cf["lcr_score"] = round((comp_available / comp_required) * 100, 1) if comp_required else 0.0
        cf["lcr_tier"] = compute_lcr_tier(cf["lcr_score"])

    # return facts info about each competitor
    return {
        "url": url,
        "company_name": company_name,
        "competitors": competitors,
        "competitor_facts": competitor_facts,
        "pillar_1_globalization": {
            **pillar1,
            "lcr_score": lcr,
            "lcr_tier": lcr_tier,
            "lcr_available": len(lcr_available_langs),
            "lcr_required": len(lcr_required_langs),
        },
        "pillar_2_website_health": pillar2 or {
            "note": "PageSpeed data not available."
        },
        "pillar_3_accessibility": pillar3,
        "pillar_4_online_reputation": pillar4,
    }

def generate_ui_content(facts: dict) -> dict:
    """
    Generate all UI-ready text for the results dashboard.
    Uses GPT-5 from the facts pack directly — no web search needed.
    Returns structured dict: executive_summary, per-pillar content, competitive_landscape, top_recommendations.
    """
    p1 = facts["pillar_1_globalization"]
    p2 = facts["pillar_2_website_health"]
    p3 = facts["pillar_3_accessibility"]
    p4 = facts["pillar_4_online_reputation"]
    cf = facts["competitor_facts"]
    company_name = facts["company_name"]
    url = facts["url"]

    # Social media concise summary (followers + last active)
    social = p4.get("social_media", {})
    social_summary = ", ".join(
        f"{platform}: {d.get('followers') or d.get('subscribers') or 'N/A'} followers"
        + (f" (last active: {d['last_active']})" if d.get("last_active") else "")
        for platform, d in social.items()
        if isinstance(d, dict) and d.get("url")
    ) or "No active profiles"

    # Mixed language issues
    ml_issues = p1.get("mixed_language_issues", [])
    ml_summary = f"{len(ml_issues)} locale(s) affected" if ml_issues else "None detected"

    # Competitor summary
    comp_summary = "\n".join(
        f"- {c.get('company_name', f'Competitor {i+1}')}: "
        f"{len(c.get('available_languages', []))} languages, LCR {c.get('lcr_score', 'N/A')}%, "
        f"sentiment {c.get('overall_sentiment', 'N/A')}, LinkedIn {c.get('linkedin_followers', 'N/A')}, "
        f"WCAG: {c.get('wcag_level_claimed', 'undeclared')}, brand: {c.get('brand_recognition', 'N/A')}"
        for i, c in enumerate(cf)
    )

    # PSI summary
    perf_mobile = p2.get("performance_score_mobile")
    perf_desktop = p2.get("performance_score_desktop")
    site_health = p2.get("site_health_score")
    psi_summary = (
        f"Mobile performance {perf_mobile}/100, desktop {perf_desktop}/100, site health {site_health}/100"
        if perf_mobile is not None
        else "PageSpeed data not available"
    )

    _p2_data_note = ""
    if p2.get("psi_ran") is False and p2.get("crawl_ran") is False:
        _p2_data_note = (
            "\nNOTE: No PSI or crawl data was collected for this site. "
            "Do not fabricate performance scores or crawl metrics. "
            "Base findings only on the HTTPS, HSTS, schema, and sitemap values provided. "
            "If data is insufficient for 3 findings, produce fewer rather than padding with generic statements."
        )

    prompt = f"""You are a senior digital audit expert writing a concise, punchy executive dashboard for a pre-audit report.

Company: {company_name}
Website: {url}

PILLAR 1 - GLOBALIZATION:
- Available languages: {p1.get('available_languages', [])} ({p1.get('lcr_available', 0)} of {p1.get('lcr_required', 0)} required)
- Required languages: {p1.get('required_languages', [])}
- LCR score: {p1.get('lcr_score', 0)}% ({p1.get('lcr_tier', 'N/A')})
- Geographic presence: {p1.get('geographic_presence', 'N/A')}
- Hreflang: {'Present' if p1.get('hreflang_present') else 'Missing' if p1.get('crawler_ran') else 'Unknown (crawler did not run)'}
- x-default: {'Present' if p1.get('hreflang_x_default_present') else 'Missing' if p1.get('crawler_ran') else 'Unknown (crawler did not run)'}
- Mixed language issues: {ml_summary}
- Translation quality: {p1.get('translation_quality_notes', 'N/A')}
- Regional/market-specific sites: {p1.get('regional_sites', [])}

PILLAR 2 - WEBSITE HEALTH:{_p2_data_note}
- {psi_summary}
- SEO score (mobile): {p2.get('seo_score_mobile', 'N/A')}, Accessibility score (mobile): {p2.get('accessibility_score_mobile', 'N/A')}
- LCP mobile: {p2.get('lcp_mobile', 'N/A')}, CLS: {p2.get('cls_mobile', 'N/A')}
- Core Web Vitals field data: LCP {p2.get('cwv_lcp_category', 'N/A')}, CLS {p2.get('cwv_cls_category', 'N/A')}, INP {p2.get('cwv_inp_category', 'N/A')}
- Performance issues: render-blocking resources: {p2.get('render_blocking_resources', False)}, unused JavaScript: {p2.get('unused_javascript', False)}, unused CSS: {p2.get('unused_css', False)}
- Pages crawled: {p2.get('pages_crawled', 0)}, broken links: {p2.get('broken_internal_urls', 0)}, missing meta descriptions: {p2.get('missing_meta_descriptions', 0)}, duplicate meta descriptions: {p2.get('duplicate_meta_pages', 0)}
- HSTS: {'Yes' if p2.get('hsts_present') else 'No'}, HTTPS redirect: {'Yes' if p2.get('https_redirect') else 'No'}
- Schema markup: {p2.get('schema_types', 'None detected')}

PILLAR 3 - ACCESSIBILITY & COMPLIANCE:
- WCAG level claimed: {p3.get('wcag_level_claimed', 'undeclared')}
- Accessibility statement: {'Yes' if p3.get('has_accessibility_statement') else 'No'}
- Cookie consent: {'Yes' if p3.get('has_cookie_banner') else 'No'}
- Applicable regulations: {p3.get('applicable_regulations', [])}
- Key issues: {p3.get('wcag_issues', [])}
- Alt text coverage: {p3.get('alt_text_coverage', 'unknown')}, Keyboard nav: {p3.get('keyboard_navigation', 'unknown')}

PILLAR 4 - ONLINE REPUTATION:
- Overall sentiment: {p4.get('overall_sentiment', 'N/A')} - {p4.get('sentiment_justification', '')}
- Social media: {social_summary}
- Trustpilot: {p4.get('trustpilot_score', 'N/A')} ({p4.get('trustpilot_reviews', 'N/A')} reviews)
- Glassdoor: {p4.get('glassdoor_score', 'N/A')} ({p4.get('glassdoor_reviews', 'N/A')} reviews)
- Indeed: {p4.get('indeed_score', 'N/A')} ({p4.get('indeed_reviews', 'N/A')} reviews)
- Trade fair presence: {p4.get('trade_fair_presence', [])}
- Credibility assets: {p4.get('credibility_assets', [])}
- Recent news: {p4.get('recent_news', [])}
- Controversies: {p4.get('controversies', [])}

COMPETITORS:
{comp_summary}

Write in US English. No em dashes. No markdown links or citations. Professional but direct tone.
Each finding and recommendation must be one concise sentence. Include specific numbers where available.

Return ONLY a valid JSON object with no markdown fences:
{{
  "executive_summary": [
    "Cross-pillar bullet 1 - most impactful finding with a specific number",
    "Cross-pillar bullet 2 - second most important gap or strength",
    "Cross-pillar bullet 3 - key competitive or compliance insight"
  ],
  "pillar_1": {{
    "headline": "Short 6-10 word headline summarizing globalization status",
    "findings": ["Finding with specific data", "Finding 2", "Finding 3"],
    "recommendations": ["Top action 1", "Top action 2", "Top action 3"]
  }},
  "pillar_2": {{
    "headline": "Short 6-10 word headline summarizing website health",
    "findings": ["Finding with specific data", "Finding 2", "Finding 3"],
    "recommendations": ["Top action 1", "Top action 2", "Top action 3"]
  }},
  "pillar_3": {{
    "headline": "Short 6-10 word headline summarizing accessibility status",
    "findings": ["Finding with specific data", "Finding 2", "Finding 3"],
    "recommendations": ["Top action 1", "Top action 2", "Top action 3"]
  }},
  "pillar_4": {{
    "headline": "Short 6-10 word headline summarizing online reputation",
    "findings": ["Finding with specific data", "Finding 2", "Finding 3"],
    "recommendations": ["Top action 1", "Top action 2", "Top action 3"]
  }},
  "competitive_landscape": {{
    "summary": "2-3 sentences positioning the client within the competitive set",
    "client_advantages": ["Advantage 1", "Advantage 2"],
    "client_gaps": ["Gap 1 vs specific competitor", "Gap 2"]
  }},
  "top_recommendations": [
    "Priority 1 cross-pillar action with expected impact",
    "Priority 2 cross-pillar action",
    "Priority 3 cross-pillar action",
    "Priority 4 cross-pillar action",
    "Priority 5 cross-pillar action"
  ]
}}"""

    try:
        resp = client.responses.create(
            model="gpt-5",
            input=prompt,
        )
        usage = getattr(resp, "usage", None)
        if usage:
            plog(
                f"[audit] generate_ui_content tokens: "
                f"input={getattr(usage, 'input_tokens', '?')} "
                f"output={getattr(usage, 'output_tokens', '?')}"
            )
        raw = resp.output_text
        return _parse_json(raw)
    except Exception as e:
        plog(f"[audit] generate_ui_content failed: {e}")
        return {}


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------

def run_audit(job_id: str, url: str, company_name: str, competitors: list) -> dict:
    """
    Run the full audit pipeline with I/O and competitor work parallelized.
    Pillar 2 (DataForSEO + PSI) and each competitor's full chain (Playwright crawl
    + GPT call) run on background threads. The main thread runs Turn 1, Turn 2,
    Pillar 4, and UI content GPT calls sequentially.
    company_name and competitors are supplied by the user.
    Returns a structured dict with all generated content.
    """
    _ctx.job_id = job_id[:8]
    plog(f"[audit] Starting audit for {url} ({company_name})")

    # start with all imports up front across different pillars, before pool starts 
    gather_pillar1_facts = None
    gather_mixed_language_issues = None
    try:
        from app.pillar1_gather import gather_pillar1_facts, gather_mixed_language_issues
    except ImportError as _import_err:
        plog(f"[audit] WARNING: Could not import pillar1_gather: {_import_err}")

    _gather_p2 = None
    try:
        try:
            from app.website_health import gather_pillar2_facts as _gather_p2
        except ImportError:
            from website_health import gather_pillar2_facts as _gather_p2
    except Exception as e:
        plog(f"[audit] WARNING: Could not import website_health: {e}")

    _gather_p4 = None
    try:
        try:
            from app.pillar4_gather import gather_pillar4_facts as _gather_p4
        except ImportError:
            from pillar4_gather import gather_pillar4_facts as _gather_p4
    except Exception as e:
        plog(f"[audit] WARNING: Could not import pillar4_gather: {e}")

    # helper to check if a url's domain resolves, to avoid wasting time for dead domains. 
    def _dns_resolves(raw_url: str) -> bool:
        try:
            hostname = urlparse(raw_url).hostname or ""
            socket.getaddrinfo(hostname, None)
            return True
        except socket.gaierror:
            return False

    # helper to run competitor chain (crawler + GPT) for a single competitor, on a background thread
    def _run_competitor_full(comp_url: str) -> dict:
        _ctx.job_id = job_id[:8]
        if not _dns_resolves(comp_url):
            plog(f"[audit]   Comp DNS lookup failed ({comp_url}) — skipping.")
            return {"company_name": comp_url, "available_languages": [], "required_languages": []}
        comp_langs = None
        if gather_pillar1_facts:
            try:
                result = gather_pillar1_facts(comp_url)
                if result.get("crawler_ran"):
                    comp_langs = result.get("available_languages")
                    if len(comp_langs or []) <= 1:
                        plog(f"[audit]   Comp crawler returned <=1 locale ({comp_url}) — GPT will fill in.")
                        comp_langs = None
                    else:
                        plog(f"[audit]   Comp crawler OK ({comp_url}): {comp_langs}")
                else:
                    plog(f"[audit]   Comp crawler failed ({comp_url}): {result.get('crawler_error', 'unknown')}")
            except Exception as e:
                plog(f"[audit]   Comp crawler exception ({comp_url}): {e}")
        try:
            comp_data = gather_competitor_benchmark_data(comp_url, crawler_available_languages=comp_langs)
            if comp_langs is not None:
                comp_data["available_languages"] = comp_langs
            return comp_data
        except Exception as e:
            plog(f"[audit]   Comp GPT failed ({comp_url}): {e}")
            return {"company_name": comp_url, "available_languages": comp_langs or [], "required_languages": []}

    # Launch background threads:
    # max_workers=4: 1 for Pillar 2 (DataForSEO + PSI), 3 for competitor full chains. All start at same time as main thread. 
    # Main thread: GPT calls (Turn 1, Turn 2, Pillar 4, UI content) remain sequential.
    pool = ThreadPoolExecutor(max_workers=4)
    if _gather_p2:
        def _run_pillar2():
            _ctx.job_id = job_id[:8]
            if not _dns_resolves(url):
                plog(f"[p2] DNS lookup failed for {urlparse(url).hostname} — skipping PSI and DataForSEO.")
                return {"psi_ran": False, "crawl_ran": False, "crawl_error": "DNS resolution failed"}
            return _gather_p2(url, max_crawl_pages=200)
        fut_pillar2 = pool.submit(_run_pillar2)
    else:
        fut_pillar2 = None
    fut_comp_fulls = [pool.submit(_run_competitor_full, c) for c in competitors]

    try:
        # Phase 0: Playwright crawler - client site (main thread, critical path)
        plog("[audit] Phase 0: Running Playwright crawler for client site...")
        client_crawler = None
        try:
            if gather_pillar1_facts:
                client_crawler = gather_pillar1_facts(url)
                if client_crawler.get("crawler_ran"):
                    plog(f"[audit]   Crawler OK: {client_crawler.get('available_languages')} | "
                         f"hreflang: {client_crawler.get('hreflang_present')} | "
                         f"x-default: {client_crawler.get('hreflang_x_default_present')}")
                    # Sanity check: if only 1 locale detected, the crawler likely hit a
                    # JS-rendering race or was blocked,drop available_languages so GPT fills
                    # it in, but keep hreflang/locale_urls/cookie data which are still valid.
                    if len(client_crawler.get("available_languages", [])) <= 1:
                        plog("[audit]   Crawler returned <=1 locale — treating as failed, GPT will research languages.")
                        client_crawler = None
                    if client_crawler and gather_mixed_language_issues:
                        plog("[audit]   Running GPT-5 mixed language check...")
                        ml_issues = gather_mixed_language_issues(
                            url, client_crawler.get("locale_urls", {})
                        )
                        client_crawler["mixed_language_issues"] = ml_issues
                        plog(f"[audit]   Mixed language issues found: {len(ml_issues)}")
                else:
                    _crawler_error = client_crawler.get("crawler_error", "")
                    plog(f"[audit]   Crawler did not run: {_crawler_error}")
                    if "ERR_NAME_NOT_RESOLVED" in _crawler_error:
                        raise ValueError(f"Domain does not exist or could not be reached: {url}")
                    client_crawler = None
            else:
                plog("[audit]   Crawler not available, skipping.")
        except ValueError:
            raise
        except Exception as e:
            plog(f"[audit]   Crawler exception: {e}")
            client_crawler = None

        # Phase 1: Gather client data (Turns 1+2: globalization + accessibility)
        plog("[audit] Phase 1: Gathering client data (Turns 1+2)...")
        pillar1_data, pillar3_data = gather_all_client_data(
            url, company_name, crawler_facts=client_crawler
        )

        # Phase 1b: Gather Pillar 4 (online reputation) via pillar4_gather pipeline
        plog("[audit] Phase 1b: Gathering Pillar 4 (online reputation)...")
        pillar4_data = {}
        try:
            if _gather_p4:
                pillar4_data = _gather_p4(url, company_name)
                # normalize review counts to integers when they have letters
                for _field in ("trustpilot_reviews", "glassdoor_reviews", "indeed_reviews"):
                    _val = pillar4_data.get(_field)
                    if isinstance(_val, str):
                        pillar4_data[_field] = _parse_review_count(_val)
                plog(f"[audit]   Pillar 4 complete. Sentiment: {pillar4_data.get('overall_sentiment', 'N/A')}")
        except Exception as e:
            plog(f"[audit]   Pillar 4 gathering failed: {e}")
            pillar4_data = {}

        # Merge crawler-only fields into pillar1_data 
        pillar1_data["crawler_ran"] = bool(client_crawler and client_crawler.get("crawler_ran"))
        if client_crawler and client_crawler.get("crawler_ran"):
            pillar1_data["locale_urls"] = client_crawler.get("locale_urls", {})
            pillar1_data["hreflang_tags"] = client_crawler.get("hreflang_tags", [])
            pillar1_data["hreflang_x_default_present"] = client_crawler.get("hreflang_x_default_present", False)
            pillar1_data["hreflang_x_default_url"] = client_crawler.get("hreflang_x_default_url")
            pillar1_data["mixed_language_issues"] = client_crawler.get("mixed_language_issues", [])
            pillar1_data["pages_checked"] = client_crawler.get("pages_checked", 0)
            pillar1_data["target_languages"] = client_crawler.get("target_languages", [])
            pillar1_data["available_language_variants"] = client_crawler.get(
                "available_language_variants", client_crawler.get("available_languages", [])
            )
            # Override authoritative fields in case GPT deviated from injected values
            pillar1_data["available_languages"] = client_crawler.get(
                "available_languages", pillar1_data.get("available_languages", [])
            )
            pillar1_data["hreflang_present"] = client_crawler.get(
                "hreflang_present", pillar1_data.get("hreflang_present", False)
            )
            pillar1_data["language_selector_type"] = client_crawler.get(
                "language_selector_type", pillar1_data.get("language_selector_type", "unknown")
            )

        # Collect competitor full-chain results (crawl+GPT ran on background threads)
        plog("[audit] Collecting competitor results...")
        competitor_facts = []
        for i, fut in enumerate(fut_comp_fulls):
            try:
                comp_data = fut.result()
            except Exception as e:
                plog(f"[audit]   Comp {i+1} future failed: {e}")
                comp_data = {"company_name": competitors[i], "available_languages": [], "required_languages": []}
            competitor_facts.append(comp_data)

        # Collect Pillar 2 result (DataForSEO done well before this point for most sites)
        pillar2_data = None
        if fut_pillar2:
            try:
                pillar2_data = fut_pillar2.result()
                plog(f"[audit]   Pillar 2 complete. "
                     f"PSI ran: {pillar2_data.get('psi_ran')}, "
                     f"Crawl ran: {pillar2_data.get('crawl_ran')}, "
                     f"Health score: {pillar2_data.get('site_health_score')}")
            except Exception as e:
                plog(f"[audit]   Pillar 2 gathering failed: {e}")

        # Override GPT's has_sitemap guess with authoritative value from website_health HTTP check
        if pillar2_data and pillar2_data.get("has_sitemap_xml") is not None:
            pillar3_data["has_sitemap"] = pillar2_data["has_sitemap_xml"]

    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    plog("[audit] Building facts pack...")
    facts = build_facts_pack(
        url, company_name, competitors,
        pillar1_data, pillar3_data, pillar4_data,
        competitor_facts,
        pillar2=pillar2_data,
    )

    # Phase 4: Generate UI content directly from facts pack (GPT-5)
    plog("[audit] Generating UI content from facts pack...")
    ui_content = generate_ui_content(facts)

    plog("[audit] Done!")

    return {
        "facts": facts,
        "ui_content": ui_content,
    }
