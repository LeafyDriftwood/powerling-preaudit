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
from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


# Helper

def _parse_json(text: str, label: str = "") -> dict:
    """Parse JSON from a model response, stripping markdown fences if present."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        prefix = f"[{label}] " if label else ""
        print(f"{prefix}JSON parse error: {e}")
        print(f"{prefix}Response length: {len(text)} chars")
        print(f"{prefix}Last 300 chars: {text[-300:]!r}")
        try:
            from json_repair import repair_json
            repaired = repair_json(text)
            result = json.loads(repaired)
            print(f"{prefix}Recovered via json_repair.")
            return result
        except Exception:
            pass
        # Try to extract a JSON object from within the text (handles preamble/postamble)
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            print(f"{prefix}Attempting extraction from embedded JSON block...")
            return json.loads(match.group())
        raise


def gather_all_client_data(url: str, company_name: str, crawler_facts: dict = None) -> tuple:
    """
    Gather client Pillar 1 and Pillar 3 data via two independent gpt-4o-search-preview calls.

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
        # Format mixed-language issues for injection
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
                else:
                    detail_parts.append(
                        f"{locale} page ({page_url}): French strings found: {iss.get('french_strings_found', [])}"
                    )
            ml_detail = "; ".join(detail_parts)
        else:
            ml_detail = "None detected (all locale pages checked)"

        # Truncate to first 5 issues to keep prompt length manageable
        ml_detail_json = json.dumps(ml_issues[:5], ensure_ascii=False)
        locale_urls_json = json.dumps(crawler_facts.get("locale_urls", {}), ensure_ascii=False)
        hreflang_tags_count = len(crawler_facts.get("hreflang_tags", []))
        print(f"[audit]   hreflang tags count: {hreflang_tags_count}")
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
    mixed_language_ux_issues_detail: {ml_detail_json}
  mixed_language_ux_issues: {ml_detail}

STEP 1 - Research the company's geographic presence:
Search for where {company_name} operates, sells, or has customers. Look for:
- Number of countries and specific regions (Europe, APAC, MENA, Americas, CEE, etc.)
- International distributor network, subsidiaries, or office locations
- Press releases, About pages, or annual reports mentioning global reach or country count

STEP 2 - Search for any separate regional websites or market-specific domains beyond {url}.
For each found, note: domain name, primary language served, target market.

STEP 3 - Derive Required Languages (RL) from the geographic footprint found in Step 1:
RL definition: identify the top 5-8 countries by traffic share using SimilarWeb or equivalent.
Map each country to its dominant official or commercial language.
RL = the distinct languages needed to serve those markets natively — no more, no fewer.
required_languages must reflect the company's actual significant customer base,
not what is already on the website and not an assumption about what a company "should" have.
Primary method: derive from traffic data (SimilarWeb top countries).
Fallback (if traffic data is paywalled or unavailable): use the geographic footprint from Step 1
to estimate the top markets by business volume, then map those to dominant languages.
Document which method was used in lcr_notes. Never return an empty list — a best-effort
estimate from geographic presence is always better than no data.

STEP 4 - Available Languages (AL) validation rule:
AL counts ONLY languages where the FULL user experience is available:
navigation, product catalog, cart, checkout, and customer service all in that language.
Do NOT count: partial translations, footer-only language switches, blog-only languages,
or third-party subdomains not part of the main site.
The crawler has already confirmed the available languages above. Use those exact values.

STEP 5 - Note translation quality on the website:
Any observations on machine vs. professional translation, inconsistencies, or untranslated sections.

STEP 6 - Traffic data:
Approximate monthly organic traffic volume (from public sources if findable), and top 3-5 traffic source countries.

Return ONLY a valid JSON object with no markdown fences.
Only return the fields below — do NOT include available_languages, language_selector_type,
locale_urls, hreflang_present, pages_checked, target_languages,
or mixed_language_ux_issues_detail as those are already known:
IMPORTANT: The JSON below shows field names and value types ONLY. Do NOT copy these example values — replace every value with your actual research findings above.
{{
  "geographic_presence": "[your actual finding: regions and country count]",
  "required_languages": ["XX", "XX"],
  "mixed_language_ux_issues": "[brief plain-text summary, or 'None detected']",
  "translation_quality_notes": "[your actual finding]",
  "lcr_notes": "[your actual finding]",
  "estimated_monthly_traffic": "[your actual finding or 'unknown']",
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
RL definition: identify the top 5-8 countries by traffic share using SimilarWeb or equivalent.
Map each country to its dominant official or commercial language.
RL = the distinct languages needed to serve those markets natively — no more, no fewer.
required_languages must reflect the company's actual significant customer base,
not what is already on the website and not an assumption about what a company "should" have.
Primary method: derive from traffic data (SimilarWeb top countries).
Fallback (if traffic data is paywalled or unavailable): use the geographic footprint from Step 1
to estimate the top markets by business volume, then map those to dominant languages.
Document which method was used in lcr_notes. Never return an empty list — a best-effort
estimate from geographic presence is always better than no data.

STEP 3 - Determine Available Languages (AL) from the website:
AL counts ONLY languages where the FULL user experience is available:
navigation, product catalog, cart, checkout, and customer service all in that language.
Do NOT count: partial translations, footer-only language switches, blog-only languages,
or third-party subdomains not part of the main site.
Note the type of language selector (dropdown, flags, country selector, subdomain, path prefix, etc.).
Also check: are hreflang tags present on the website?

STEP 4 - Check for mixed-language UX issues:
For example: untranslated CTAs appearing on non-matching locale pages, navigation in the wrong language,
or inconsistent locale switching. Be specific if found.

STEP 5 - Note translation quality on the website:
Any observations on machine vs. professional translation, inconsistencies, or untranslated sections.

STEP 6 - Search for any separate regional websites or market-specific domains beyond {url}.
For each found, note: domain name, primary language, target market.

STEP 7 - Traffic data:
Approximate monthly organic traffic if findable. Top 3-5 traffic source countries.

Return ONLY a valid JSON object with no markdown fences.
IMPORTANT: The JSON below shows field names and value types ONLY. Do NOT copy these example values — replace every value with your actual research findings above.
{{
  "available_languages": ["XX", "XX"],
  "language_selector_type": "[your actual finding]",
  "geographic_presence": "[your actual finding: regions and country count]",
  "required_languages": ["XX", "XX"],
  "hreflang_present": false,
  "mixed_language_ux_issues": "[brief plain-text summary, or 'None detected']",
  "translation_quality_notes": "[your actual finding]",
  "lcr_notes": "[your actual finding]",
  "estimated_monthly_traffic": "[your actual finding or 'unknown']",
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
        print(f"[audit] turn1 tokens: input={getattr(usage, 'input_tokens', '?')} output={getattr(usage, 'output_tokens', '?')}")
    p1_text = resp1.output_text
    pillar1_data = _parse_json(p1_text, label="Turn1-Globalization")
    print("[audit]   Turn 1 (Globalization) complete.")

    # ------------------------------------------------------------------
    # Turn 2: Accessibility & Compliance (independent call — avoids TPM ceiling)
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

    # Cookie banner facts from Playwright crawler (authoritative)
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
6. Is the website GDPR compliant based on visible indicators?
7. Does the website have an ADA compliance statement or mention ADA?
8. What country/region is the company primarily based in?
9. Has the company faced any accessibility-related lawsuits or complaints? Search public records.
10. Does the website have a publicly accessible sitemap?
11. What WCAG accessibility level does the website claim or appear to target? (e.g., "WCAG 2.1 AA", "WCAG 2.0 A", "RGAA v4.1 partial", "undeclared"). Check the footer, accessibility statement, and legal notices.
12. How is alt text coverage across the site? Use one of: consistent / partial / missing / unknown, and describe your actual finding with specific examples from the site.
13. How is keyboard navigation? Is there a visible "skip to content" or "skip to main" link? Any keyboard traps in navigation menus or carousels?
14. Does the website use any third-party forms or scripts that introduce trackers before consent is given? Name the specific tools found if any.
15. Are there any PDFs or downloadable documents? If so, do they appear to be text-based (selectable text, screen-reader friendly) or image-based scans?

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
  "gdpr_indicators": false,
  "ada_indicators": false,
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
        print(f"[audit] turn2 tokens: input={getattr(usage, 'input_tokens', '?')} output={getattr(usage, 'output_tokens', '?')}")
    p3_text = resp2.output_text
    pillar3_data = _parse_json(p3_text, label="Turn2-Accessibility")
    print("[audit]   Turn 2 (Accessibility) complete.")

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

    comp_prompt = f"""
Research the website {url} to gather competitive benchmark data. Search online for accurate, current information.

{lang_note}Find the following, with actual numbers wherever possible:

GLOBALIZATION:
1. What languages are available on the website? Only count full UX languages (not partial translations).{' (ALREADY CONFIRMED ABOVE - use those values)' if crawler_available_languages is not None else ''}
2. Search for the company's geographic presence (countries, regions, key markets). Based on that footprint, estimate how many languages would justify a full translated UX — counting only languages where there is a substantial customer segment, not every language in every country of operation. Return this as required_languages_count (integer).
3. Brief description of global reach (number of countries, key regions).
4. Estimated monthly traffic if findable.

ACCESSIBILITY & COMPLIANCE:
5. Accessibility statement: yes/no
6. GDPR-compliant cookie consent: yes/no
7. ADA compliance statement: yes/no
8. Any notable accessibility issues publicly reported.
9. What WCAG level does the site claim or appear to target? (e.g., "WCAG 2.1 AA", "undeclared")
10. Alt text coverage quality: consistent / partial / missing / unknown
11. Keyboard navigation quality: brief description, or "unknown"

ONLINE REPUTATION:
12. Brief factual description of their brand positioning based on what you find online.
13. Digital engagement level: High / Medium / Low (based on social following + review volume).
14. LinkedIn follower count - search directly for their LinkedIn company page by name.
15. Total social media reach estimate across all platforms.
16. Review score (Trustpilot or Google) if available.
17. Overall online sentiment (positive / neutral / negative).

Return ONLY a valid JSON object with no markdown fences.
IMPORTANT: The JSON below shows field names and value types ONLY. Do NOT copy these example values — replace every value with your actual research findings above.
{{
  "company_name": "[actual company name]",
  "available_languages": ["XX", "XX"],
  "required_languages_count": 0,
  "global_reach": "[your actual finding]",
  "estimated_monthly_traffic": "[your actual finding or 'unknown']",
  "has_accessibility_statement": false,
  "gdpr_indicators": false,
  "ada_indicators": false,
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
        print(f"[audit] competitor tokens: input={getattr(usage, 'input_tokens', '?')} output={getattr(usage, 'output_tokens', '?')}")
    return _parse_json(response.output_text)


# ---------------------------------------------------------------------------
# Step 2: Compute deterministic metrics
# ---------------------------------------------------------------------------

def compute_lcr(available_languages: list, required_languages: list) -> float:
    """Calculate Language Coverage Rate: LCR = (AL / RL) * 100."""
    if not required_languages:
        return 0.0
    return round((len(available_languages) / len(required_languages)) * 100, 1)


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
        comp_required = cf.get("required_languages_count") or len(cf.get("required_languages", []))
        comp_available = len(cf.get("available_languages", []))
        cf["lcr_score"] = round((comp_available / comp_required) * 100, 1) if comp_required else 0.0
        cf["lcr_tier"] = compute_lcr_tier(cf["lcr_score"])

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
    Output is written for salespeople: plain language, no jargon, spoken sentences.
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
        f"sentiment {c.get('overall_sentiment', 'N/A')}, LinkedIn {c.get('linkedin_followers', 'N/A')}"
        for i, c in enumerate(cf)
    )

    # PSI summary — pre-computed to prevent GPT from inventing numbers
    perf_mobile = p2.get("performance_score_mobile")
    perf_desktop = p2.get("performance_score_desktop")
    lcp_mobile = p2.get("lcp_mobile")
    site_health = p2.get("site_health_score")
    broken_links = p2.get("broken_internal_urls", 0)
    missing_metas = p2.get("missing_meta_descriptions", 0)
    psi_summary = (
        f"Mobile performance {perf_mobile}/100, desktop {perf_desktop}/100, "
        f"LCP mobile {lcp_mobile}, site health {site_health}/100, "
        f"{broken_links} broken links, {missing_metas} pages missing meta descriptions"
        if perf_mobile is not None
        else "PageSpeed data not available"
    )

    # Geographic and language facts — pre-computed to prevent GPT drift on numbers
    geographic_presence = p1.get("geographic_presence", "N/A")
    lcr_available = p1.get("lcr_available", 0)
    lcr_required = p1.get("lcr_required", 0)
    lcr_score = p1.get("lcr_score", 0)
    lcr_tier = p1.get("lcr_tier", "N/A")
    available_languages = p1.get("available_languages", [])
    required_languages = p1.get("required_languages", [])
    missing_languages = [lang for lang in required_languages if lang not in available_languages]

    # Reputation facts — pre-computed so GPT uses exact values
    trustpilot_score = p4.get("trustpilot_score")
    trustpilot_reviews = p4.get("trustpilot_reviews")
    google_score = p4.get("google_reviews_score")
    google_count = p4.get("google_reviews_count")
    glassdoor_score = p4.get("glassdoor_score")
    indeed_score = p4.get("indeed_score")

    prompt = f"""You are writing the pre-call briefing card for a salesperson.
The salesperson has 2 minutes before a prospect call. They are not technical. They need sentences they can say out loud, not metrics, not acronyms, not audit jargon.

Company being audited: {company_name} ({url})

FACTS (use these exact numbers — do not invent or alter them):

GLOBALIZATION:
- Geographic presence: {geographic_presence}
- Languages on the website: {lcr_available} of {lcr_required} required ({", ".join(available_languages)})
- Missing languages: {", ".join(missing_languages) if missing_languages else "None"}
- Language mixing issues across locale pages: {ml_summary}
- Language coverage: {lcr_score}% ({lcr_tier})

WEBSITE HEALTH:
- {psi_summary}

ACCESSIBILITY:
- Accessibility statement published: {"Yes" if p3.get("has_accessibility_statement") else "No"}
- Cookie consent present: {"Yes" if p3.get("has_cookie_banner") else "No"}
- Applicable regulations: {p3.get("applicable_regulations", [])}
- Key issues detected: {p3.get("wcag_issues", [])}

ONLINE REPUTATION:
- Trustpilot: {f"{trustpilot_score}/5 ({trustpilot_reviews} reviews)" if trustpilot_score else "No profile found"}
- Google Reviews: {f"{google_score}/5 ({google_count} reviews)" if google_score else "None found"}
- Glassdoor: {f"{glassdoor_score}/5" if glassdoor_score else "N/A"}
- Indeed: {f"{indeed_score}/5" if indeed_score else "N/A"}
- Social media: {social_summary}
- Overall sentiment: {p4.get("overall_sentiment", "N/A")}

COMPETITORS:
{comp_summary}

ROI BENCHMARKS (use only the ones relevant to each pillar — cite the source in parentheses):
- Globalization: companies investing in localization report 20-30% revenue growth vs non-localized peers (Nimdzi Insights). 75% of online consumers prefer to buy when product info is in their native language (CSA Research).
- Website Health: a 1-second reduction in load time yields approximately 7% improvement in conversion rate (Google/Deloitte). Technical SEO remediation produces 30-42% organic traffic growth within 3-6 months in documented cases (Backlinko).
- Accessibility: accessible websites reach an additional 15-20% of potential users (WHO). EU non-compliance exposes businesses to fines of 5,000 to 250,000 euros per violation depending on member state (EAA, enforceable June 2025).
- Online Reputation: a 1-star improvement on major review platforms correlates with 5-9% revenue increase (Harvard Business Review). Businesses that respond to reviews see 45% higher likelihood of customer selection (Google Consumer Survey).

WRITING RULES — follow all of these exactly:

1. Zero technical jargon in the executive summary and pillar cards. No acronyms: no LCR, LCP, CLS, WCAG, RGAA, hreflang, CTR, SERP, BCP 47, INP, FCP, TBT. Write as if explaining to a smart non-technical person.

2. Write findings as problems the PROSPECT has, not observations about their website. "They are invisible in Germany" not "German locale has missing hreflang tags."

3. Write recommendations as business outcomes, not technical tasks. "Reach 7 more markets" not "implement hreflang for missing locales."

4. Determine traffic lights from these thresholds using the facts above:
   - Globalization: red if coverage below 30%, orange if 30-60%, green if above 60%
   - Website Health: red if mobile performance score below 50, orange if 50-70, green if above 70
   - Accessibility: red if no accessibility statement and EU-based company, orange if partial, green if compliant
   - Online Reputation: red if no reviews at all, orange if best available score below 4.0, green if score at or above 4.0

5. objection_handler is one sentence the salesperson says when the prospect pushes back. Make it competitive and concrete, referencing a named competitor where possible.

6. severity_rank: rank the four pillars 1 (most critical) to 4 (least critical) based on the facts. The executive_summary bullets must follow this ranking order.

7. Executive summary bullets are spoken sentences about the prospect. Start each with a relevant emoji (choose from: ⚠️ 🐌 ⚖️ 📉 🌍 🔇 🔗 👻). Example: "They sell in 27 countries but only speak 3 languages — 24 markets cannot understand their website."

8. Each pillar has exactly 2 supporting_facts. One sentence each, written as prospect pain, no jargon.

9. roi_sentence: one sentence per pillar using a relevant benchmark from the ROI BENCHMARKS above. State an assumption before applying the benchmark. Present as a range, not a single figure. Label it a projection. Example: "Assuming estimated monthly traffic of 50,000 sessions, a 1-second load time improvement could lift conversions by approximately 7%, a projection based on Google and Deloitte research."

10. No em dashes. Use periods or commas instead. No filler phrases (no "essentially," "basically," "actually"). No formal transitions (no "moreover," "furthermore," "in conclusion").

11. Pull all country and language counts from the FACTS section above. Do not invent or round numbers.

Return ONLY a valid JSON object with no markdown fences:
{{
  "executive_summary": [
    "emoji Sentence about the most critical problem, written as something a salesperson can say out loud",
    "emoji Sentence about the second most critical problem",
    "emoji Sentence about the third most critical problem"
  ],
  "pillar_1": {{
    "traffic_light": "red",
    "headline": "One plain-language sentence summarizing the language situation",
    "supporting_facts": [
      "Prospect pain written as a business problem, no jargon",
      "Second prospect pain, ideally with a named competitor comparison"
    ],
    "objection_handler": "One sentence for when the prospect says they already know about this",
    "roi_sentence": "One sentence projection using a relevant benchmark, with stated assumption and range",
    "severity_rank": 1
  }},
  "pillar_2": {{
    "traffic_light": "orange",
    "headline": "One plain-language sentence summarizing the site performance situation",
    "supporting_facts": [
      "Prospect pain written as a business problem",
      "Second prospect pain"
    ],
    "objection_handler": "One sentence for handling pushback",
    "roi_sentence": "One sentence projection using a relevant benchmark, with stated assumption and range",
    "severity_rank": 2
  }},
  "pillar_3": {{
    "traffic_light": "red",
    "headline": "One plain-language sentence summarizing the legal or compliance situation",
    "supporting_facts": [
      "Prospect pain written as a business problem",
      "Second prospect pain"
    ],
    "objection_handler": "One sentence for handling pushback",
    "roi_sentence": "One sentence projection using a relevant benchmark, with stated assumption and range",
    "severity_rank": 3
  }},
  "pillar_4": {{
    "traffic_light": "green",
    "headline": "One plain-language sentence summarizing the reputation situation",
    "supporting_facts": [
      "Prospect pain written as a business problem",
      "Second prospect pain"
    ],
    "objection_handler": "One sentence for handling pushback",
    "roi_sentence": "One sentence projection using a relevant benchmark, with stated assumption and range",
    "severity_rank": 4
  }},
  "competitive_landscape": {{
    "summary": "2-3 sentences positioning the client versus named competitors in plain language",
    "client_advantages": ["Advantage 1 in plain language", "Advantage 2"],
    "client_gaps": ["Gap versus a specific named competitor", "Gap 2"]
  }},
  "top_recommendations": [
    "Business outcome 1 — what changes and why it matters commercially",
    "Business outcome 2",
    "Business outcome 3",
    "Business outcome 4",
    "Business outcome 5"
  ]
}}"""

    try:
        resp = client.responses.create(
            model="gpt-5",
            input=prompt,
        )
        usage = getattr(resp, "usage", None)
        if usage:
            print(
                f"[audit] generate_ui_content tokens: "
                f"input={getattr(usage, 'input_tokens', '?')} "
                f"output={getattr(usage, 'output_tokens', '?')}"
            )
        raw = resp.output_text
        return _parse_json(raw)
    except Exception as e:
        print(f"[audit] generate_ui_content failed: {e}")
        return {}


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------

def run_audit(url: str, company_name: str, competitors: list) -> dict:
    """
    Run the full audit pipeline sequentially.
    company_name and competitors are supplied by the user.
    Returns a structured dict with all generated content.
    """
    print(f"[audit] Starting audit for {url} ({company_name})")

    # Phase 0: Playwright crawler - client site
    try:
        from app.pillar1_gather import gather_pillar1_facts, gather_mixed_language_issues
    except ImportError as _import_err:
        print(f"[audit] WARNING: Could not import pillar1_gather: {_import_err}")
        gather_pillar1_facts = None
        gather_mixed_language_issues = None

    print("[audit] Phase 0: Running Playwright crawler for client site...")
    client_crawler = None
    try:
        if gather_pillar1_facts:
            client_crawler = gather_pillar1_facts(url)
            if client_crawler.get("crawler_ran"):
                print(f"[audit]   Crawler OK: {client_crawler.get('available_languages')} | "
                      f"hreflang: {client_crawler.get('hreflang_present')} | "
                      f"x-default: {client_crawler.get('hreflang_x_default_present')}")
                if gather_mixed_language_issues:
                    print("[audit]   Running GPT-5 mixed language check...")
                    ml_issues = gather_mixed_language_issues(
                        url, client_crawler.get("locale_urls", {})
                    )
                    client_crawler["mixed_language_issues"] = ml_issues
                    print(f"[audit]   Mixed language issues found: {len(ml_issues)}")
            else:
                print(f"[audit]   Crawler did not run: {client_crawler.get('crawler_error')}")
                client_crawler = None
        else:
            print("[audit]   Crawler not available, skipping.")
    except Exception as e:
        print(f"[audit]   Crawler exception: {e}")
        client_crawler = None

    # Phase 1: Gather client data (Turns 1+2: globalization + accessibility)
    print("[audit] Phase 1: Gathering client data (Turns 1+2)...")
    pillar1_data, pillar3_data = gather_all_client_data(
        url, company_name, crawler_facts=client_crawler
    )

    # Phase 1b: Gather Pillar 4 (online reputation) via pillar4_gather pipeline
    print("[audit] Phase 1b: Gathering Pillar 4 (online reputation)...")
    pillar4_data = {}
    try:
        try:
            from app.pillar4_gather import gather_pillar4_facts as _gather_p4
        except ImportError:
            from pillar4_gather import gather_pillar4_facts as _gather_p4
        pillar4_data = _gather_p4(url, company_name)
        # Coerce review count fields from strings to ints (safety net for "50,000+" etc.)
        for _field in ("google_reviews_count", "trustpilot_reviews", "glassdoor_reviews", "indeed_reviews"):
            _val = pillar4_data.get(_field)
            if isinstance(_val, str):
                _cleaned = re.sub(r"[^\d]", "", _val)
                pillar4_data[_field] = int(_cleaned) if _cleaned else None
        print(f"[audit]   Pillar 4 complete. Sentiment: {pillar4_data.get('overall_sentiment', 'N/A')}")
    except Exception as e:
        print(f"[audit]   Pillar 4 gathering failed: {e}")
        pillar4_data = {}

    # Merge crawler-only fields into pillar1_data (these never come from GPT)
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

    # Phase 0b: Gather Pillar 2 (DataForSEO crawl + PSI + homepage checks)
    # Runs after the Playwright crawler so locale_urls are available.
    print("[audit] Phase 0b: Gathering Pillar 2 website health data...")
    pillar2_data = None
    try:
        try:
            from app.website_health import gather_pillar2_facts as _gather_p2
        except ImportError:
            from website_health import gather_pillar2_facts as _gather_p2
        pillar2_data = _gather_p2(url, max_crawl_pages=200)
        print(f"[audit]   Pillar 2 complete. "
              f"PSI ran: {pillar2_data.get('psi_ran')}, "
              f"Crawl ran: {pillar2_data.get('crawl_ran')}, "
              f"Health score: {pillar2_data.get('site_health_score')}")
    except Exception as e:
        print(f"[audit]   Pillar 2 gathering failed: {e}")
        pillar2_data = None

    # Override GPT's has_sitemap guess with authoritative value from website_health HTTP check
    if pillar2_data and pillar2_data.get("has_sitemap_xml") is not None:
        pillar3_data["has_sitemap"] = pillar2_data["has_sitemap_xml"]

    # Phase 2: Crawl + gather competitor benchmark data (one crawler + one search call each)
    competitor_facts = []
    for i, comp_url in enumerate(competitors):
        print(f"[audit] Phase 2: Crawling competitor {i+1} ({comp_url})...")
        try:
            comp_crawler = gather_pillar1_facts(comp_url) if gather_pillar1_facts else None
            comp_langs = comp_crawler.get("available_languages") if (comp_crawler and comp_crawler.get("crawler_ran")) else None
            if comp_langs is not None:
                print(f"[audit]   Competitor {i+1} crawler OK: {comp_langs}")
            else:
                err = comp_crawler.get("crawler_error") if comp_crawler else "crawler not available"
                print(f"[audit]   Competitor {i+1} crawler failed: {err}")
        except Exception as e:
            print(f"[audit]   Competitor {i+1} crawler exception: {e}")
            comp_langs = None

        print(f"[audit]   Gathering competitor {i+1} data via search ({comp_url})...")
        try:
            comp_data = gather_competitor_benchmark_data(comp_url, crawler_available_languages=comp_langs)
            # Ensure crawler's available_languages takes precedence
            if comp_langs is not None:
                comp_data["available_languages"] = comp_langs
        except Exception as e:
            print(f"[audit]   Competitor {i+1} data gathering failed: {e}")
            comp_data = {"company_name": comp_url, "available_languages": comp_langs or [], "required_languages": []}
        competitor_facts.append(comp_data)

    print("[audit] Building facts pack...")
    facts = build_facts_pack(
        url, company_name, competitors,
        pillar1_data, pillar3_data, pillar4_data,
        competitor_facts,
        pillar2=pillar2_data,
    )

    # Phase 4: Generate UI content directly from facts pack (GPT-5)
    print("[audit] Generating UI content from facts pack...")
    ui_content = generate_ui_content(facts)

    print("[audit] Done!")

    return {
        "facts": facts,
        "ui_content": ui_content,
    }
