"""
Audit pipeline for Powerling Pre-Audit system.

Steps:
1. Gather client data via a stateful 3-turn conversation (web search)
2. Gather each competitor's benchmark data via individual search calls
3. Compute deterministic metrics (LCR)
4. Build Facts Pack
5. Generate pillar content sequentially via GPT-4o writing calls
6. Generate Competitive Landscape + Conclusion
7. Return structured report dict

API strategy:
- Data gathering (needs web search): gpt-4o-search-preview via Chat Completions
- Content generation (no search needed): gpt-4o via Chat Completions
- One unified API surface (Chat Completions) throughout.
"""

import json
import os
import re
from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


# Helper

def _parse_json(text: str) -> dict:
    """Parse JSON from a model response, stripping markdown fences if present."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text.strip())


# Step 1: Data Gathering  #
# Client data: stateful 3-turn conversation so each question builds on the last.
# Competitor data: one call per competitor covering all benchmark dimensions.
# Might overuse tokens but ensures context carries through

def gather_all_client_data(url: str, company_name: str, crawler_facts: dict = None) -> tuple:
    """
    Gather all three pillars of client data using a single stateful conversation.
    Turn 1 -> Globalization
    Turn 2 -> Accessibility & Compliance (model already has site context from Turn 1)
    Turn 3 -> Online Reputation (model already knows company region, size, etc.)

    crawler_facts: if provided and crawler_ran=True, structural language facts are
    injected as authoritative and GPT focuses on market/geographic research instead.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert digital auditor. You research websites thoroughly using web search "
                "to gather accurate, quantitative information. Always return valid JSON with no markdown fences."
            ),
        }
    ]

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

        ml_detail_json = json.dumps(ml_issues, ensure_ascii=False)
        locale_urls_json = json.dumps(crawler_facts.get("locale_urls", {}), ensure_ascii=False)
        hreflang_tags_json = json.dumps(crawler_facts.get("hreflang_tags", []), ensure_ascii=False)
        target_langs_json = json.dumps(crawler_facts.get("target_languages", []), ensure_ascii=False)
        available_lang_variants_json = json.dumps(
            crawler_facts.get("available_language_variants", crawler_facts.get("available_languages", [])),
            ensure_ascii=False,
        )

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
    available_language_variants: {available_lang_variants_json}
  language_selector_type: "{crawler_facts['language_selector_type']}"
    locale_urls: {locale_urls_json}
  hreflang_present: {crawler_facts['hreflang_present']}
    hreflang_tags: {hreflang_tags_json}
  hreflang_x_default: {x_default_status}
    pages_checked: {crawler_facts.get('pages_checked', 0)}
    target_languages_checked_for_mixing: {target_langs_json}
    mixed_language_ux_issues_detail: {ml_detail_json}
  mixed_language_ux_issues: {ml_detail}

STEP 1 - Research the company's geographic presence:
Search online for where {company_name} operates, sells, or has customers. Look for:
- How many countries they are present in and which specific regions (Europe, APAC, MENA, Americas, CEE, etc.)
- Their international distributor network, subsidiaries, or office locations
- Any press releases, About pages, or annual reports mentioning global reach or country count

STEP 2 - Search for any separate regional websites or market-specific domains operated by {company_name} beyond {url}.
Examples: a French subdomain, a country-specific TLD (.de, .fr), a separate shop or portal.
For each found, note the domain name, primary language served, and target market.

STEP 3 - Derive required languages from the geographic footprint found in Step 1:
IMPORTANT: required_languages must reflect the company's ACTUAL global reach - NOT just the languages currently on the website.
Example: a company operating in 90+ countries across Europe, MENA, APAC, and Latin America needs Arabic, Mandarin, Japanese, Korean, Russian, Turkish, Polish, etc. - even if those are not currently on the site.

STEP 4 - Note translation quality on the website:
Any observations on machine vs. professional translation, inconsistencies, or untranslated sections.

STEP 5 - Traffic data:
Approximate monthly organic traffic volume (from public sources if findable), and top 3-5 traffic source countries.

Return ONLY a valid JSON object with no markdown fences:
{{
  "available_languages": {crawler_facts['available_languages']},
    "available_language_variants": {available_lang_variants_json},
  "language_selector_type": "{crawler_facts['language_selector_type']}",
    "locale_urls": {locale_urls_json},
  "geographic_presence": "Present in 90+ countries across Europe (65%), MENA (7.5%), APAC (7.5%), Latin America (7.5%), North America (5%)",
  "required_languages": ["EN", "FR", "DE", "ES", "IT", "PT", "NL", "AR", "ZH", "JA", "KO", "RU", "TR", "PL"],
  "hreflang_present": {str(crawler_facts['hreflang_present']).lower()},
    "hreflang_tags": {hreflang_tags_json},
    "pages_checked": {crawler_facts.get('pages_checked', 0)},
    "target_languages": {target_langs_json},
    "mixed_language_ux_issues_detail": {ml_detail_json},
  "mixed_language_ux_issues": "{ml_detail}",
  "translation_quality_notes": "...",
  "lcr_notes": "...",
  "estimated_monthly_traffic": "500K-1M",
  "top_traffic_countries": ["FR", "DE", "US"],
  "regional_sites": [{{"domain": "example-fr.com", "language": "FR", "market": "France", "note": "Separate French market website"}}]
}}
"""
    else:
        turn1_prompt = f"""
You are auditing the website {url} for globalization.

STEP 1 - Research the company's geographic presence FIRST before looking at the website:
Search online for where this company operates, sells, or has customers. Look for:
- How many countries they are present in and which specific regions (Europe, APAC, MENA, Americas, CEE, etc.)
- Their international distributor network, subsidiaries, or office locations
- Any press releases, About pages, or annual reports mentioning global reach or country count

STEP 2 - Check the website for language availability:
1. What languages are available via the language/country selector on the website?
   Only count languages where the FULL user experience (navigation, product catalog, cart, checkout) is available.
   Do NOT count partial translations or blog-only languages.
2. What type of language selector is used? (dropdown, flags, country selector, subdomain, path prefix like /en/, etc.)
3. Are there any mixed-language UX issues? For example: untranslated CTAs ("En savoir plus") appearing on non-French pages, navigation labels in the wrong language, or inconsistent locale switching. Be specific if found.
4. Are hreflang tags present on the website?
5. Any notes on translation quality (machine translation vs. professional, inconsistencies, etc.)?
6. Approximate monthly organic traffic volume if findable (from public sources like SimilarWeb estimates).
7. What are the top 3-5 traffic source countries?

STEP 3 - Search for any separate regional websites or market-specific domains operated by this company beyond {url}.
For each found, note: domain name, primary language, target market.

STEP 4 - Derive required languages from the geographic footprint found in Step 1:
IMPORTANT: required_languages must reflect the company's ACTUAL global reach - NOT just the languages currently on the website.
Example: a company operating in 90+ countries across Europe, MENA, APAC, and Latin America needs Arabic, Mandarin, Japanese, Korean, Russian, Turkish, Polish, etc. - even if those are not currently on the site.

Return ONLY a valid JSON object with no markdown fences:
{{
  "available_languages": ["EN", "FR", "DE"],
  "language_selector_type": "dropdown with flags",
  "geographic_presence": "Present in 90+ countries across Europe (65%), MENA (7.5%), APAC (7.5%), Latin America (7.5%), North America (5%)",
  "required_languages": ["EN", "FR", "DE", "ES", "IT", "PT", "NL", "AR", "ZH", "JA", "KO", "RU", "TR", "PL"],
  "hreflang_present": false,
  "mixed_language_ux_issues": "French CTAs ('En savoir plus') appear on German and English locale pages",
  "translation_quality_notes": "...",
  "lcr_notes": "...",
  "estimated_monthly_traffic": "500K-1M",
  "top_traffic_countries": ["FR", "DE", "US"],
  "regional_sites": []
}}
"""

    messages.append({"role": "user", "content": turn1_prompt})

    resp1 = client.chat.completions.create(model="gpt-4o-search-preview", messages=messages)
    p1_text = resp1.choices[0].message.content
    messages.append({"role": "assistant", "content": p1_text})
    pillar1_data = _parse_json(p1_text)
    print("[audit]   Turn 1 (Globalization) complete.")

    # ------------------------------------------------------------------
    # Turn 2: Accessibility & Compliance
    # ------------------------------------------------------------------
    messages.append({"role": "user", "content": f"""
Now audit the same website ({url}) for accessibility and legal compliance.

Search the website and answer the following:
1. Does the website have an accessibility statement? (yes/no, and URL if yes)
2. Does the website have a cookie banner/consent mechanism? (yes/no, and provider if known e.g. OneTrust, Cookiebot)
3. Does the website have a privacy policy? (yes/no)
4. Does the website have a terms of service / terms of use? (yes/no)
5. Are there any obvious WCAG accessibility issues (missing alt text, poor contrast, no skip navigation, missing form labels, etc.)?
6. Is the website GDPR compliant based on visible indicators?
7. Does the website have an ADA compliance statement or mention ADA?
8. What country/region is the company primarily based in?
9. Has the company faced any accessibility-related lawsuits or complaints? Search public records.
10. Does the website have a publicly accessible sitemap?
11. What WCAG accessibility level does the website claim or appear to target? (e.g., "WCAG 2.1 AA", "WCAG 2.0 A", "RGAA v4.1 partial", "undeclared"). Check the footer, accessibility statement, and legal notices.
12. How is alt text coverage across the site? Be specific: describe what you found (e.g., "consistent - most images have descriptive alt", "partial - some images use generic 'Image' text while others are descriptive", "missing - alt largely absent"). Note specific examples if found.
13. How is keyboard navigation? Is there a visible "skip to content" or "skip to main" link? Any keyboard traps in navigation menus or carousels?
14. Does the website use any third-party forms or scripts (e.g., Google reCAPTCHA, chat widgets, analytics) that introduce trackers before consent is given?
15. Are there any PDFs or downloadable documents? If so, do they appear to be text-based (selectable text, screen-reader friendly) or image-based scans?

Return ONLY a valid JSON object with no markdown fences:
{{
  "has_accessibility_statement": false,
  "accessibility_statement_url": null,
  "has_cookie_banner": true,
  "cookie_provider": "OneTrust",
  "has_privacy_policy": true,
  "has_terms_of_service": true,
  "has_sitemap": true,
  "wcag_issues": ["missing alt text on hero image", "low contrast on footer links"],
  "wcag_level_claimed": "undeclared",
  "alt_text_coverage": "partial - mix of descriptive alt and generic 'Image' on homepage modules",
  "keyboard_navigation": "Skip link present on key templates; full keyboard coverage unverified",
  "third_party_forms": "Google reCAPTCHA on contact and distributor forms",
  "pdf_accessibility": "Text-based brochure PDFs found; structural tagging not verified",
  "gdpr_indicators": true,
  "ada_indicators": false,
  "primary_region": "France",
  "applicable_regulations": ["GDPR", "CNIL", "RGAA"],
  "accessibility_lawsuits": []
}}
"""})

    resp2 = client.chat.completions.create(model="gpt-4o-search-preview", messages=messages)
    p3_text = resp2.choices[0].message.content
    messages.append({"role": "assistant", "content": p3_text})
    pillar3_data = _parse_json(p3_text)
    print("[audit]   Turn 2 (Accessibility) complete.")

    # ------------------------------------------------------------------
    # Turn 3: Online Reputation
    # ------------------------------------------------------------------
    messages.append({"role": "user", "content": f"""
Now audit the online reputation of the same company ({company_name}, {url}).

For social media: search each platform directly by company name. Even if exact real-time counts are unavailable, provide your best estimate from any recent public data. Do not return null if an approximation is findable - use "approx. X" if needed.

Search online and answer the following:
1. Social media presence - search each platform directly:
   - LinkedIn: search "{company_name} LinkedIn" for their company page URL and follower count
   - X (Twitter): search for their official handle, note follower count and most recent post date
   - Instagram: search "{company_name} Instagram" for profile URL and follower count
   - Facebook: search "{company_name} Facebook" for page URL and like/follower count
   - YouTube: search "{company_name} YouTube" for channel URL and subscriber count
2. Trustpilot profile? Score (out of 5), total number of reviews, and response rate if available.
3. Google Reviews? Score and approximate number of reviews.
4. Glassdoor profile? Rating, number of reviews, CEO approval rating, and "recommend to a friend" percentage if available.
5. G2 or Capterra profile? Score and number of reviews if applicable (B2B companies).
6. Any regulatory approvals, certifications, or industry authorizations that serve as credibility assets (e.g., ISO certifications, government biocide authorizations, CE marks, awards). Include dates if found.
7. Any trade fair, conference, or industry event presence noted online (e.g., MEDICA, CPhI, Interclean). List by name and year.
8. Notable news articles, press releases, or industry coverage in the past 12-18 months. Include source and date where possible.
9. Any known controversies, lawsuits, data breaches, or reputational issues?
10. Overall brand sentiment online (positive / neutral / negative) with a brief justification.

Return ONLY a valid JSON object with no markdown fences:
{{
  "social_media": {{
    "linkedin": {{"url": "https://linkedin.com/company/...", "followers": "1.5K"}},
    "twitter": {{"url": "https://twitter.com/...", "followers": "approx. 400", "last_active": "2023"}},
    "instagram": {{"url": "https://instagram.com/...", "followers": "268"}},
    "facebook": {{"url": "https://facebook.com/...", "followers": "289"}},
    "youtube": {{"url": "https://youtube.com/...", "subscribers": "approx. 100"}}
  }},
  "trustpilot_score": null,
  "trustpilot_reviews": null,
  "trustpilot_response_rate": null,
  "google_reviews_score": null,
  "google_reviews_count": null,
  "glassdoor_score": 3.4,
  "glassdoor_reviews": 10,
  "glassdoor_ceo_approval": "76%",
  "glassdoor_recommend": "76%",
  "g2_score": null,
  "g2_reviews": null,
  "credibility_assets": ["EU Union Authorisation for H2O2 biocide product (Sept 2023)", "ISO 9001 certified"],
  "trade_fair_presence": ["MEDICA 2024", "World Health Expo Dubai 2026"],
  "recent_news": ["Company receives EU biocide authorization - press release, Sept 2023"],
  "controversies": [],
  "overall_sentiment": "neutral",
  "sentiment_justification": "Limited public reviews but positive credibility through regulatory certifications and trade fair presence."
}}
"""})

    resp3 = client.chat.completions.create(model="gpt-4o-search-preview", messages=messages)
    p4_text = resp3.choices[0].message.content
    pillar4_data = _parse_json(p4_text)
    print("[audit]   Turn 3 (Online Reputation) complete.")

    return pillar1_data, pillar3_data, pillar4_data


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

    response = client.chat.completions.create(
        model="gpt-4o-search-preview",
        messages=[
            {"role": "user", "content": f"""
Research the website {url} to gather competitive benchmark data. Search online for accurate, current information.

{lang_note}Find the following, with actual numbers wherever possible:

GLOBALIZATION:
1. What languages are available on the website? Only count full UX languages (not partial translations).{' (ALREADY CONFIRMED ABOVE - use those values)' if crawler_available_languages is not None else ''}
2. Search for the company's geographic presence first (countries, regions, distributor network). Then derive required languages based on that footprint - NOT from the available languages. A company in 50+ countries likely needs more than what is on the website.
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
12. Brief brand recognition description (e.g., "Global leader in bio-decontamination", "Regional player in DACH").
13. Digital engagement level: High / Medium / Low (based on social following + review volume).
14. LinkedIn follower count - search directly for their LinkedIn company page by name.
15. Total social media reach estimate across all platforms.
16. Review score (Trustpilot or Google) if available.
17. Overall online sentiment (positive / neutral / negative).

Return ONLY a valid JSON object with no markdown fences:
{{
  "company_name": "Competitor Inc",
  "available_languages": ["EN", "FR"],
  "required_languages": ["EN", "FR", "DE", "ES", "ZH", "JA"],
  "global_reach": "Present in 50+ countries across Europe and Asia",
  "estimated_monthly_traffic": "200K-500K",
  "has_accessibility_statement": false,
  "gdpr_indicators": true,
  "ada_indicators": false,
  "wcag_level_claimed": "undeclared",
  "alt_text_coverage": "partial",
  "keyboard_navigation": "unknown",
  "wcag_issues_noted": [],
  "brand_recognition": "Global leader in bio-decontamination solutions",
  "digital_engagement": "Medium",
  "linkedin_followers": "15K",
  "social_media_reach": "~40K followers across all platforms",
  "review_score": 4.1,
  "overall_sentiment": "positive"
}}
"""}
        ],
    )
    return _parse_json(response.choices[0].message.content)


# ---------------------------------------------------------------------------
# Step 2: Compute deterministic metrics
# ---------------------------------------------------------------------------

def compute_lcr(available_languages: list, required_languages: list) -> float:
    """Calculate Language Coverage Rate: LCR = (AL / RL) * 100."""
    if not required_languages:
        return 0.0
    return round((len(available_languages) / len(required_languages)) * 100, 1)


def compute_lcr_tier(lcr: float) -> str:
    """Return Powerling LCR tier label (Score 1/3, 2/3, or 3/3)."""
    if lcr < 50:
        return "Score 1/3"
    elif lcr <= 75:
        return "Score 2/3"
    else:
        return "Score 3/3"


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
    lcr = compute_lcr(pillar1["available_languages"], pillar1["required_languages"])
    lcr_tier = compute_lcr_tier(lcr)

    # Compute LCR and tier for each competitor
    for cf in competitor_facts:
        cf["lcr_score"] = compute_lcr(
            cf.get("available_languages", []),
            cf.get("required_languages", [])
        )
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
            "lcr_available": len(pillar1["available_languages"]),
            "lcr_required": len(pillar1["required_languages"]),
        },
        "pillar_2_website_health": pillar2 or {
            "note": "PageSpeed data not available."
        },
        "pillar_3_accessibility": pillar3,
        "pillar_4_online_reputation": pillar4,
    }


# ---------------------------------------------------------------------------
# Step 4: Generate pillar content  (gpt-4o — no web search, writing only)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a senior audit expert for Powerling, a localization and digital presence firm.
You write pre-audit reports with outstanding professional quality, in a professional tone that is understandable to a general business audience.
You only use the facts explicitly provided to you in the prompt. Never invent, assume, or estimate data.
You are auditing ONLY the specific website URL provided. Do not reference other websites or properties the same company may own.

Formatting rules:
- Bold (**word**) important terms across every section. Do not abuse it - only truly key terms.
- No em dashes anywhere. Use regular hyphens or commas instead.
- No hyperlinks anywhere in the audit text or table cells.
- Write in US English.
- Do not mention "SEMrush" by name. Use "SEO diagnostic tool" instead.
- Do not name specific vendors or third-party service providers in recommendations.
- Do not include LCR formula or calculations in the output - only the final result percentage.
- Write in a natural, professional style. Avoid patterns that sound AI-generated."""


def generate_pillar1(facts: dict) -> dict:
    p1 = facts["pillar_1_globalization"]
    company_name = facts["company_name"]
    cf = facts["competitor_facts"]

    # Format locale_urls: which URL serves each language
    locale_urls = p1.get("locale_urls", {})
    locale_url_str = (
        "\n".join(f"    {lang}: {href}" for lang, href in locale_urls.items())
        if locale_urls else "  Not available"
    )
    available_variants = p1.get("available_language_variants", p1.get("available_languages", []))

    # x-default status
    if p1.get("hreflang_x_default_present"):
        x_default_str = f"Present, pointing to {p1.get('hreflang_x_default_url')}"
    elif p1.get("hreflang_present"):
        x_default_str = "Hreflang tags present but no x-default tag found"
    else:
        x_default_str = "No hreflang tags at all"

    # Detailed mixed-language issues from crawler
    ml_issues = p1.get("mixed_language_issues", [])
    if ml_issues:
        ml_lines = []
        for iss in ml_issues:
            locale = iss.get("locale", "?")
            page_url = iss.get("page_url", "?")
            hits = iss.get("language_hits", [])
            if hits:
                for hit in hits:
                    lang = hit.get("language", "?")
                    strings = hit.get("marker_strings_found", [])
                    ml_lines.append(f"    Locale '{locale}' ({page_url}): {lang} text found - {strings}")
            else:
                strings = iss.get("french_strings_found", [])
                ml_lines.append(f"    Locale '{locale}' ({page_url}): French text found - {strings}")
        ml_detail_str = "\n".join(ml_lines)
    else:
        ml_detail_str = "  None detected"

    # Regional / separate market sites from GPT
    regional_sites = p1.get("regional_sites", [])
    if regional_sites:
        regional_str = "\n".join(
            f"    {s.get('domain')} - {s.get('language')} / {s.get('market')}"
            + (f" ({s.get('note')})" if s.get("note") else "")
            for s in regional_sites
        )
    else:
        regional_str = "  None identified"

    # Competitors: use N/A* for LCR since required_languages can't be fully audited
    competitor_data_str = "\n".join(
        f"- {c.get('company_name', f'Competitor {i+1}')}: "
        f"{len(c.get('available_languages', []))} languages {c.get('available_languages', [])}, "
        f"LCR N/A*, "
        f"reach: {c.get('global_reach', 'N/A')}, "
        f"traffic: {c.get('estimated_monthly_traffic', 'N/A')}"
        for i, c in enumerate(cf)
    )

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"""
Write Pillar 1: Globalization for {company_name} ({facts['url']}).

CLIENT FACTS - use these exactly, do not change any numbers:
- Geographic presence: {p1.get('geographic_presence', 'N/A')}
- Available languages (confirmed by direct analysis):
{locale_url_str}
- Available language variants (raw locale tags): {available_variants}
- Language selector type: {p1['language_selector_type']}
- Required languages (based on geographic footprint): {p1['required_languages']}
- LCR score: {p1['lcr_score']}% - {p1['lcr_tier']} ({p1['lcr_available']} of {p1['lcr_required']} required languages covered)
- Hreflang tags: {p1['hreflang_present']}
- Hreflang entries detected: {len(p1.get('hreflang_tags', []))}
- Hreflang x-default: {x_default_str}
- Mixed-language UX issues (confirmed by direct page analysis):
{ml_detail_str}
- Locale pages checked by crawler: {p1.get('pages_checked', 0)}
- Translation quality notes: {p1.get('translation_quality_notes', 'N/A')}
- Additional LCR notes: {p1.get('lcr_notes', 'N/A')}
- Estimated monthly traffic: {p1.get('estimated_monthly_traffic', 'N/A')}
- Top traffic countries: {p1.get('top_traffic_countries', [])}
- Separate regional / market-specific sites operated by {company_name}:
{regional_str}

COMPETITOR BENCHMARK DATA - already researched, use as-is:
{competitor_data_str}

Write the following sections:
1. pillar_intro: One sentence introducing what this pillar assesses.
2. key_findings_intro: An introductory paragraph (3-4 sentences) that uses the geographic presence and language gap to set context. Reference the number of required languages vs. available languages.
3. key_findings_bullets: 5-7 bullet points covering:
   - One bullet must state the LCR result as "{p1['lcr_score']}% - {p1['lcr_tier']}". Do not include the LCR formula.
   - Language selector type and whether hreflang tags are present.
   - Hreflang x-default status and its SEO implications (if x-default is missing, note this as a gap; if present, confirm it is configured).
   - If mixed-language UX issues were found, include a specific bullet citing the locale and the foreign-language strings observed.
   - If regional/separate market sites were identified, include a bullet noting this fragmented presence.
   - Translation quality observations if notable.
4. impact: Text-only paragraph discussing the business impact. No bullet points. Address: missed organic traffic from missing language markets, SEO penalties from absent hreflang/x-default configuration, user trust erosion from mixed-language UX, and missed revenue from underserved regions. Be specific to the company's markets.
5. recommendations: Exactly 5 actionable bullet points. Recommendations should cover:
   - Specific high-priority languages to add based on geographic gaps (name the languages).
   - Hreflang implementation with x-default and canonical tag alignment.
   - Mixed-language UX fixes if issues were found.
   - Translation quality upgrade path (if applicable).
   - A fifth recommendation on either sitemap localization, regional site consolidation, or CMS localization workflow.
6. expected_roi: Text-only paragraph with specific ROI percentage ranges tied to the findings (e.g., organic traffic lift, conversion improvement, lead volume). Vary the ranges based on the severity of the gaps found.
7. benchmark_table: Columns are Organization, Global Reach, Languages Covered, LCR Score.
   - First row is the client using the exact facts above.
   - Remaining rows use the competitor benchmark data above, marked with "(est.)" where applicable.
   - LCR Score cells: use "{p1['lcr_score']}% - {p1['lcr_tier']}" for the client, and "N/A*" for all competitors.

Return as JSON:
{{
  "pillar_intro": "...",
  "key_findings_intro": "...",
  "key_findings_bullets": ["...", "..."],
  "impact": "...",
  "recommendations": ["...", "..."],
  "expected_roi": "...",
  "benchmark_table": {{
    "columns": ["Organization", "Global Reach", "Languages Covered", "LCR Score"],
    "rows": [
      ["{company_name}", "...", "{p1['lcr_available']} languages", "{p1['lcr_score']}% - {p1['lcr_tier']}"],
      ["...", "...", "...", "N/A*"],
      ["...", "...", "...", "N/A*"],
      ["...", "...", "...", "N/A*"]
    ]
  }},
  "benchmark_note": "Competitor language data is estimated from publicly available information. LCR marked N/A* for competitors as a full required-language audit was not conducted on these websites."
}}
"""}
        ]
    )
    return _parse_json(response.choices[0].message.content)


def generate_pillar3(facts: dict) -> dict:
    p3 = facts["pillar_3_accessibility"]
    company_name = facts["company_name"]
    cf = facts["competitor_facts"]

    stmt_url = p3.get("accessibility_statement_url") or "URL not found"
    accessibility_stmt = f"Yes, at {stmt_url}" if p3.get("has_accessibility_statement") else "No"
    cookie_info = (
        f"Yes, using {p3.get('cookie_provider') or 'unknown provider'}"
        if p3.get("has_cookie_banner") else "No"
    )

    competitor_data_str = "\n".join(
        f"- {c.get('company_name', f'Competitor {i+1}')}: "
        f"WCAG level: {c.get('wcag_level_claimed', 'undeclared')}, "
        f"Accessibility statement: {'Yes' if c.get('has_accessibility_statement') else 'No'}, "
        f"Alt text: {c.get('alt_text_coverage', 'unknown')}, "
        f"Keyboard nav: {c.get('keyboard_navigation', 'unknown')}"
        for i, c in enumerate(cf)
    )

    regulations = p3.get('applicable_regulations', [])
    reg_str = ", ".join(regulations) if regulations else "GDPR"

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"""
Write Pillar 3: Accessibility & Compliance for {company_name} ({facts['url']}).

CLIENT FACTS - use these exactly:
- Primary region: {p3.get('primary_region', 'Unknown')}
- Applicable regulations: {reg_str}
- WCAG level claimed: {p3.get('wcag_level_claimed', 'undeclared')}
- Accessibility statement: {accessibility_stmt}
- Alt text coverage: {p3.get('alt_text_coverage', 'unknown')}
- Keyboard navigation: {p3.get('keyboard_navigation', 'unknown')}
- Third-party forms/trackers: {p3.get('third_party_forms', 'None identified')}
- PDF accessibility: {p3.get('pdf_accessibility', 'Not assessed')}
- Cookie banner: {cookie_info}
- Privacy policy: {'Yes' if p3.get('has_privacy_policy') else 'No'}
- Terms of service: {'Yes' if p3.get('has_terms_of_service') else 'No'}
- Public sitemap: {'Yes' if p3.get('has_sitemap') else 'No'}
- WCAG issues found: {p3.get('wcag_issues', [])}
- Accessibility lawsuits/complaints: {p3.get('accessibility_lawsuits', [])}

COMPETITOR BENCHMARK DATA - already researched, use as-is:
{competitor_data_str}

Write the following sections:
1. pillar_intro: One sentence introducing what this pillar assesses.
2. key_findings_intro: An introductory paragraph (3-4 sentences). Reference the applicable regulatory context (e.g., CNIL for French companies, GDPR for EU, RGAA for French public sites).
3. key_findings_bullets: 5-7 bullet points. Be specific: mention reCAPTCHA/third-party forms if found, cite the exact WCAG issues, mention the skip link if present, note PDF accessibility status.
4. impact: Text-only paragraph discussing legal exposure and UX impact. No bullet points. Reference specific regulations and their enforcement context where relevant (e.g., CNIL sanctions).
5. recommendations: Exactly 5 actionable bullet points. Reference specific frameworks (WCAG 2.1 AA, RGAA v4.1, GDPR/CNIL) in the recommendations.
6. expected_roi: Text-only paragraph with specific ROI percentage ranges tied to the findings.
7. benchmark_table: Columns are Organization, WCAG 2.1 Level, Accessibility Statement, Alt Text Coverage, Keyboard Navigation.
   - First row is the client using the exact facts above.
   - Remaining rows use the competitor benchmark data above.

Return as JSON:
{{
  "pillar_intro": "...",
  "key_findings_intro": "...",
  "key_findings_bullets": ["...", "..."],
  "impact": "...",
  "recommendations": ["...", "..."],
  "expected_roi": "...",
  "benchmark_table": {{
    "columns": ["Organization", "WCAG 2.1 Level", "Accessibility Statement", "Alt Text Coverage", "Keyboard Navigation"],
    "rows": [
      ["{company_name}", "...", "...", "...", "..."],
      ["...", "...", "...", "...", "..."],
      ["...", "...", "...", "...", "..."],
      ["...", "...", "...", "...", "..."]
    ]
  }},
  "benchmark_note": "Competitor data is estimated based on publicly available information and industry benchmarks, as a formal audit was not conducted on these websites."
}}
"""}
        ]
    )
    return _parse_json(response.choices[0].message.content)


def generate_pillar4(facts: dict) -> dict:
    p4 = facts["pillar_4_online_reputation"]
    company_name = facts["company_name"]
    cf = facts["competitor_facts"]

    # Flatten social media for clean display in prompt
    social = p4.get("social_media", {})
    social_str = ", ".join(
        f"{platform}: {data.get('followers') or data.get('subscribers') or 'N/A'} followers"
        for platform, data in social.items()
        if isinstance(data, dict) and data.get("url")
    ) or "No active profiles found"

    competitor_data_str = "\n".join(
        f"- {c.get('company_name', f'Competitor {i+1}')}: "
        f"Brand recognition: {c.get('brand_recognition', 'N/A')}, "
        f"Engagement: {c.get('digital_engagement', 'N/A')}, "
        f"Social reach: {c.get('social_media_reach', 'N/A')} (LinkedIn: {c.get('linkedin_followers', 'N/A')}), "
        f"Review score: {c.get('review_score', 'N/A')}, "
        f"Sentiment: {c.get('overall_sentiment', 'N/A')}"
        for i, c in enumerate(cf)
    )

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"""
Write Pillar 4: Online Reputation for {company_name} ({facts['url']}).

CLIENT FACTS - use these exactly:
- Social media presence: {social_str}
- Trustpilot: {p4.get('trustpilot_score', 'N/A')} score ({p4.get('trustpilot_reviews', 'N/A')} reviews, {p4.get('trustpilot_response_rate', 'N/A')} response rate)
- Google Reviews: {p4.get('google_reviews_score', 'N/A')} score ({p4.get('google_reviews_count', 'N/A')} reviews)
- Glassdoor: {p4.get('glassdoor_score', 'N/A')} rating ({p4.get('glassdoor_reviews', 'N/A')} reviews, CEO approval: {p4.get('glassdoor_ceo_approval', 'N/A')}, recommend to a friend: {p4.get('glassdoor_recommend', 'N/A')})
- G2/Capterra: {p4.get('g2_score', 'N/A')} score ({p4.get('g2_reviews', 'N/A')} reviews)
- Credibility assets: {p4.get('credibility_assets', [])}
- Trade fair presence: {p4.get('trade_fair_presence', [])}
- Recent news: {p4.get('recent_news', [])}
- Controversies: {p4.get('controversies', [])}
- Overall sentiment: {p4.get('overall_sentiment', 'N/A')} - {p4.get('sentiment_justification', '')}

COMPETITOR BENCHMARK DATA - already researched, use as-is:
{competitor_data_str}

Write the following sections:
1. pillar_intro: One sentence introducing what this pillar assesses.
2. key_findings_intro: An introductory paragraph (3-4 sentences). Mention the primary social channel and the overall credibility picture.
3. key_findings_bullets: 5-7 bullet points. Include specific numbers for all platforms where available. Include a bullet on credibility assets (certifications, authorizations) and trade fair presence if found. Use actual follower counts from the facts above.
4. impact: Text-only paragraph discussing the impact of the current online footprint on brand trust, talent acquisition, and market reach. No bullet points.
5. recommendations: Exactly 5 actionable bullet points with concrete actions (e.g., posting frequency targets, specific platform priorities, review solicitation strategy).
6. expected_roi: Text-only paragraph with specific ROI percentage ranges tied to the findings (e.g., follower growth %, CTR improvement, brand engagement lift).
7. benchmark_table: Columns are Organization, Brand Recognition, Digital Engagement, Social Media Reach, Online Sentiment.
   - First row is the client using the exact facts above. Use the actual follower counts.
   - Remaining rows use the competitor benchmark data above.

Return as JSON:
{{
  "pillar_intro": "...",
  "key_findings_intro": "...",
  "key_findings_bullets": ["...", "..."],
  "impact": "...",
  "recommendations": ["...", "..."],
  "expected_roi": "...",
  "benchmark_table": {{
    "columns": ["Organization", "Brand Recognition", "Digital Engagement", "Social Media Reach", "Online Sentiment"],
    "rows": [
      ["{company_name}", "...", "...", "...", "..."],
      ["...", "...", "...", "...", "..."],
      ["...", "...", "...", "...", "..."],
      ["...", "...", "...", "...", "..."]
    ]
  }},
  "benchmark_note": "Competitor data is estimated based on publicly available information and industry benchmarks, as a formal audit was not conducted on these websites."
}}
"""}
        ]
    )
    return _parse_json(response.choices[0].message.content)


def generate_competitive_landscape(facts: dict, pillar_summaries: dict) -> dict:
    company_name = facts["company_name"]
    cf = facts["competitor_facts"]

    p1_context = pillar_summaries.get("pillar_1", {}).get("key_findings_intro", "")
    p3_context = pillar_summaries.get("pillar_3", {}).get("key_findings_intro", "")
    p4_context = pillar_summaries.get("pillar_4", {}).get("key_findings_intro", "")

    competitor_summary = "\n".join(
        f"- {c.get('company_name', f'Competitor {i+1}')}: "
        f"Languages: {len(c.get('available_languages', []))} (LCR {c.get('lcr_score', 'N/A')}% - {c.get('lcr_tier', 'N/A')}), "
        f"WCAG: {c.get('wcag_level_claimed', 'undeclared')}, "
        f"Accessibility stmt: {'Yes' if c.get('has_accessibility_statement') else 'No'}, "
        f"LinkedIn: {c.get('linkedin_followers', 'N/A')}, "
        f"Sentiment: {c.get('overall_sentiment', 'N/A')}, "
        f"Reach: {c.get('global_reach', 'N/A')}"
        for i, c in enumerate(cf)
    )

    p1 = facts["pillar_1_globalization"]
    p3 = facts["pillar_3_accessibility"]
    p4 = facts["pillar_4_online_reputation"]

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"""
Write the Competitive Landscape section for {company_name} ({facts['url']}).

Client audit summary:
- Globalization: LCR {p1['lcr_score']}% - {p1['lcr_tier']}, {p1['lcr_available']} languages, geographic presence: {p1.get('geographic_presence', 'N/A')}
- Accessibility: WCAG level {p3.get('wcag_level_claimed', 'undeclared')}, accessibility statement: {'Yes' if p3.get('has_accessibility_statement') else 'No'}, issues: {p3.get('wcag_issues', [])}
- Online Reputation: sentiment {p4.get('overall_sentiment', 'N/A')}, LinkedIn {p4.get('social_media', dict()).get('linkedin', dict()).get('followers', 'N/A')} followers

Already-written pillar summaries for context:
- Globalization: {p1_context}
- Accessibility: {p3_context}
- Online Reputation: {p4_context}

COMPETITOR BENCHMARK DATA - already researched, use as-is for the table:
{competitor_summary}

Instructions:
1. Write a two-sentence intro paragraph that positions the client within the competitive set.
2. Build a landscape table with rows = 4 pillars, columns = client + 3 competitors.
   - Use short company names (not full URLs) as column headers for competitors.
   - Each cell must be data-dense, max 15 words. Use actual numbers from the facts above.
   - Mark competitor cells with "(est.)" where data is estimated.
   - Website Health row: since no diagnostic data is available for any company, note this briefly for all columns.

Return as JSON:
{{
  "intro": "...",
  "table": {{
    "headers": ["{company_name}", "{cf[0].get('company_name', 'Competitor 1')}", "{cf[1].get('company_name', 'Competitor 2')}", "{cf[2].get('company_name', 'Competitor 3')}"],
    "rows": [
      {{"pillar": "Globalization", "cells": ["...", "...", "...", "..."]}},
      {{"pillar": "Website Health", "cells": ["...", "...", "...", "..."]}},
      {{"pillar": "Accessibility", "cells": ["...", "...", "...", "..."]}},
      {{"pillar": "Online Reputation", "cells": ["...", "...", "...", "..."]}}
    ]
  }},
  "benchmark_note": "Competitor figures are estimated based on publicly available information and industry benchmarks. A formal audit was not conducted on these websites."
}}
"""}
        ]
    )
    return _parse_json(response.choices[0].message.content)


def generate_conclusion(facts: dict, pillar_summaries: dict) -> dict:
    company_name = facts["company_name"]

    p1_impact = pillar_summaries.get("pillar_1", {}).get("impact", "")
    p3_impact = pillar_summaries.get("pillar_3", {}).get("impact", "")
    p4_impact = pillar_summaries.get("pillar_4", {}).get("impact", "")
    p1_recs = pillar_summaries.get("pillar_1", {}).get("recommendations", [])
    p3_recs = pillar_summaries.get("pillar_3", {}).get("recommendations", [])
    p4_recs = pillar_summaries.get("pillar_4", {}).get("recommendations", [])

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"""
Write the Conclusion for the audit of {company_name} ({facts['url']}).

Already-written pillar impacts for context:
- Globalization impact: {p1_impact}
- Accessibility impact: {p3_impact}
- Online Reputation impact: {p4_impact}

Already-written pillar recommendations for context:
- Globalization: {p1_recs}
- Accessibility: {p3_recs}
- Online Reputation: {p4_recs}

Write a concise conclusion under 250 words total:
1. positives: A short paragraph summarizing what the company does well across all pillars.
2. negatives: A short paragraph summarizing the key issues found across all pillars.
3. recommendations: Exactly 5 top-level cross-pillar recommendations (synthesized from the pillar recommendations above).
4. expected_roi: A short paragraph with combined ROI estimates across pillars.

Return as JSON:
{{
  "positives": "...",
  "negatives": "...",
  "recommendations": ["...", "...", "...", "...", "..."],
  "expected_roi": "..."
}}
"""}
        ]
    )
    return _parse_json(response.choices[0].message.content)


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------

def run_audit(url: str, company_name: str, competitors: list, semrush_pdf_path: str = None) -> dict:
    """
    Run the full audit pipeline sequentially.
    company_name and competitors are supplied by the user.
    Returns a structured dict with all generated content.
    """
    print(f"[audit] Starting audit for {url} ({company_name})")

    # Phase 0: Playwright crawler - client site
    try:
        from app.crawler import gather_pillar1_facts
    except ImportError as _import_err:
        print(f"[audit] WARNING: Could not import crawler: {_import_err}")
        gather_pillar1_facts = None

    print("[audit] Phase 0: Running Playwright crawler for client site...")
    client_crawler = None
    try:
        if gather_pillar1_facts:
            client_crawler = gather_pillar1_facts(url, check_mixed_language=True)
            if client_crawler.get("crawler_ran"):
                print(f"[audit]   Crawler OK: {client_crawler.get('available_languages')} | "
                      f"hreflang: {client_crawler.get('hreflang_present')} | "
                      f"x-default: {client_crawler.get('hreflang_x_default_present')} | "
                      f"mixed-lang issues: {len(client_crawler.get('mixed_language_issues', []))}")
            else:
                print(f"[audit]   Crawler did not run: {client_crawler.get('crawler_error')}")
                client_crawler = None
        else:
            print("[audit]   Crawler not available, skipping.")
    except Exception as e:
        print(f"[audit]   Crawler exception: {e}")
        client_crawler = None

    # Phase 1: Gather client data (stateful 3-turn conversation)
    print("[audit] Phase 1: Gathering client data (stateful conversation)...")
    pillar1_data, pillar3_data, pillar4_data = gather_all_client_data(
        url, company_name, crawler_facts=client_crawler
    )

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

    # Phase 2: Crawl + gather competitor benchmark data (one crawler + one search call each)
    competitor_facts = []
    for i, comp_url in enumerate(competitors):
        print(f"[audit] Phase 2: Crawling competitor {i+1} ({comp_url})...")
        try:
            comp_crawler = gather_pillar1_facts(comp_url, check_mixed_language=False) if gather_pillar1_facts else None
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
        comp_data = gather_competitor_benchmark_data(comp_url, crawler_available_languages=comp_langs)
        # Ensure crawler's available_languages takes precedence
        if comp_langs is not None:
            comp_data["available_languages"] = comp_langs
        competitor_facts.append(comp_data)

    print("[audit] Building facts pack...")
    facts = build_facts_pack(
        url, company_name, competitors,
        pillar1_data, pillar3_data, pillar4_data,
        competitor_facts,
    )

    # Phase 3: Generate pillar content 
    print("[audit] Generating Pillar 1 (Globalization)...")
    p1_content = generate_pillar1(facts)

    print("[audit] Generating Pillar 3 (Accessibility)...")
    p3_content = generate_pillar3(facts)

    print("[audit] Generating Pillar 4 (Online Reputation)...")
    p4_content = generate_pillar4(facts)

    pillar_summaries = {
        "pillar_1": p1_content,
        "pillar_3": p3_content,
        "pillar_4": p4_content,
    }

    print("[audit] Generating Competitive Landscape...")
    landscape = generate_competitive_landscape(facts, pillar_summaries)

    print("[audit] Generating Conclusion...")
    conclusion = generate_conclusion(facts, pillar_summaries)

    print("[audit] Done!")

    return {
        "facts": facts,
        "pillar_1": p1_content,
        "pillar_2": {"note": "Google PageSpeed / SEO diagnostic integration pending."},
        "pillar_3": p3_content,
        "pillar_4": p4_content,
        "competitive_landscape": landscape,
        "conclusion": conclusion,
    }
