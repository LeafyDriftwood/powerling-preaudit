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
        raise


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

        # Truncate to first 5 issues to keep prompt length manageable
        ml_detail_json = json.dumps(ml_issues[:5], ensure_ascii=False)
        locale_urls_json = json.dumps(crawler_facts.get("locale_urls", {}), ensure_ascii=False)
        hreflang_tags = crawler_facts.get("hreflang_tags", [])
        print(f"[audit]   hreflang tags count: {len(hreflang_tags)}")
        hreflang_tags_json = json.dumps(hreflang_tags, ensure_ascii=False)
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

Return ONLY a valid JSON object with no markdown fences.
Only return the fields below — do NOT include available_languages, available_language_variants,
language_selector_type, locale_urls, hreflang_present, hreflang_tags, pages_checked,
target_languages, or mixed_language_ux_issues_detail as those are already known:
{{
  "geographic_presence": "Present in 90+ countries across Europe (65%), MENA (7.5%), APAC (7.5%), Latin America (7.5%), North America (5%)",
  "required_languages": ["EN", "FR", "DE", "ES", "IT", "PT", "NL", "AR", "ZH", "JA", "KO", "RU", "TR", "PL"],
  "mixed_language_ux_issues": "Brief plain-text summary e.g. French CTAs found on German and English locale pages",
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
    pillar1_data = _parse_json(p1_text, label="Turn1-Globalization")
    print("[audit]   Turn 1 (Globalization) complete.")

    # ------------------------------------------------------------------
    # Turn 2: Accessibility & Compliance (independent call — avoids TPM ceiling)
    # Context injected: URL, company name, available languages + locale URLs from
    # the crawler so GPT can infer the applicable regulatory framework (GDPR, RGAA,
    # ADA, etc.) without needing the full Turn 1 conversation history.
    # ------------------------------------------------------------------
    available_languages = pillar1_data.get("available_languages", [])
    locale_urls = pillar1_data.get("locale_urls", {})
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

    turn2_prompt = f"""
You are auditing the website {url} ({company_name}) for accessibility and legal compliance.

Context from direct site analysis:
- Available languages: {available_languages}
- Locale URLs: {locale_urls_json}
- Cookie consent: {cookie_instruction}

Use the languages and locale URLs above to infer the company's likely region(s) and applicable regulations (e.g., GDPR/CNIL/RGAA for French sites, ADA/WCAG for US-facing sites, EN 301 549 for EU public sector).

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
"""

    resp2 = client.chat.completions.create(
        model="gpt-4o-search-preview",
        messages=[{"role": "user", "content": turn2_prompt}],
    )
    p3_text = resp2.choices[0].message.content
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

    # Format social media with followers + last_active
    social = p4.get("social_media", {})
    social_lines = []
    for platform, data in social.items():
        if not isinstance(data, dict) or not data.get("url"):
            continue
        count = data.get("followers") or data.get("subscribers") or "N/A"
        last = data.get("last_active")
        note = data.get("note")
        line = f"  {platform}: {data['url']} | {count} followers"
        if last:
            line += f", last active: {last}"
        if note:
            line += f" ({note})"
        social_lines.append(line)
    social_str = "\n".join(social_lines) if social_lines else "  No active profiles found"

    # Format trade fair presence (list of objects)
    trade_fairs = p4.get("trade_fair_presence", [])
    if trade_fairs and isinstance(trade_fairs[0], dict):
        trade_str = "; ".join(
            f"{t.get('event')} ({t.get('location')}, {t.get('dates')})"
            for t in trade_fairs
        )
    else:
        trade_str = ", ".join(str(t) for t in trade_fairs) if trade_fairs else "None found"

    # Format controversies (list of objects or strings)
    controversies = p4.get("controversies", [])
    if controversies and isinstance(controversies[0], dict):
        controversy_str = "; ".join(
            f"{c.get('date', 'N/A')}: {c.get('issue', '')}"
            for c in controversies
        )
    else:
        controversy_str = "; ".join(str(c) for c in controversies) if controversies else "None identified"

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
Social media:
{social_str}
- Trustpilot: {p4.get('trustpilot_score', 'N/A')} score ({p4.get('trustpilot_reviews', 'N/A')} reviews)
- Google Reviews: {p4.get('google_reviews_score', 'N/A')} score ({p4.get('google_reviews_count', 'N/A')} reviews){f" ({p4['google_reviews_note']})" if p4.get('google_reviews_note') else ""}
- Glassdoor: {p4.get('glassdoor_score', 'N/A')} rating ({p4.get('glassdoor_reviews', 'N/A')} reviews, CEO approval: {p4.get('glassdoor_ceo_approval', 'N/A')}%, recommend: {p4.get('glassdoor_recommend', 'N/A')}%){f" ({p4['glassdoor_note']})" if p4.get('glassdoor_note') else ""}
- Indeed: {p4.get('indeed_score', 'N/A')} rating ({p4.get('indeed_reviews', 'N/A')} reviews){f" ({p4['indeed_note']})" if p4.get('indeed_note') else ""}
- Credibility assets: {p4.get('credibility_assets', [])}
- Trade fair presence: {trade_str}
- Recent news: {p4.get('recent_news', [])}
- Controversies: {controversy_str}
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


def _format_pillar2_facts(p2: dict) -> str:
    """
    Format Pillar 2 facts into three labeled sections for the GPT prompt.
    Only non-None values are included to keep the prompt clean.
    """
    na = "N/A"
    lines = []

    # ---- Section 1: Site Crawl (DataForSEO) ----
    if p2.get("crawl_ran"):
        pages = p2.get("pages_crawled", 0)
        score = p2.get("site_health_score")
        lines.append(f"## Site Crawl (DataForSEO OnPage, {pages} pages crawled)")
        if score is not None:
            lines.append(f"- Site health score: {score}/100")
        lines.append(f"- Broken internal URLs: {p2.get('broken_internal_urls', na)}")
        lines.append(
            f"- Redirect pages: {p2.get('redirect_pages', na)} "
            f"(permanent 301: {p2.get('permanent_redirects', na)}, "
            f"temporary 302: {p2.get('temporary_redirects', na)})"
        )
        lines.append(f"- Missing title tag: {p2.get('missing_title_pages', na)}")
        lines.append(f"- Short title (<30 chars): {p2.get('short_title_pages', na)}")
        lines.append(f"- Long title (>60 chars): {p2.get('long_title_pages', na)}")
        lines.append(f"- Duplicate titles: {p2.get('duplicate_title_pages', na)}")
        lines.append(f"- Missing meta description: {p2.get('missing_meta_descriptions', na)}")
        lines.append(f"- Duplicate meta descriptions: {p2.get('duplicate_meta_pages', na)}")
        lines.append(f"- Missing H1: {p2.get('missing_h1_pages', na)}")
        lines.append(f"- Multiple H1s: {p2.get('multiple_h1_pages', na)}")
        lines.append(f"- Missing canonical tag: {p2.get('missing_canonical_pages', na)}")
        lines.append(f"- Pages with missing alt text: {p2.get('images_missing_alt', na)}")
        lines.append(f"- Thin content pages (<300 words): {p2.get('thin_content_pages', na)}")
        if p2.get("duplicate_content_pages") is not None:
            lines.append(f"- Duplicate content pages: {p2['duplicate_content_pages']}")
        if p2.get("avg_word_count") is not None:
            lines.append(f"- Avg word count: {p2['avg_word_count']}")
        if p2.get("avg_text_to_html_ratio") is not None:
            lines.append(f"- Avg text-to-HTML ratio: {p2['avg_text_to_html_ratio']}")
        if p2.get("max_crawl_depth") is not None:
            lines.append(
                f"- Crawl depth: max {p2['max_crawl_depth']}, "
                f"avg {p2.get('avg_crawl_depth')}, "
                f"pages at depth >3: {p2.get('pages_deep_crawl')}"
            )
        if p2.get("orphan_pages") is not None:
            lines.append(f"- Pages not in sitemap: {p2['orphan_pages']}")
        if p2.get("https_to_http_links"):
            lines.append(f"- HTTPS-to-HTTP links: {p2['https_to_http_links']}")
        if p2.get("broken_resources_pages") is not None:
            lines.append(f"- Pages with broken resources (images/CSS/JS): {p2['broken_resources_pages']}")
        if p2.get("crawl_scope_note"):
            lines.append(f"  Scope: {p2['crawl_scope_note']}")
    else:
        error = p2.get("crawl_error") or "not run"
        lines.append(f"## Site Crawl\nNot available ({error}).")

    lines.append("")

    # ---- Section 2: Performance (Google PSI) ----
    lines.append("## Performance (Google PageSpeed Insights)")
    hp_m = p2.get("homepage_mobile", {})
    hp_d = p2.get("homepage_desktop", {})

    if hp_m.get("psi_ran"):
        lines.append(
            f"Homepage mobile: performance {p2.get('performance_score_mobile')}/100, "
            f"SEO {p2.get('seo_score_mobile')}/100, "
            f"accessibility {p2.get('accessibility_score_mobile')}/100"
        )
        lines.append(
            f"  LCP {p2.get('lcp_mobile') or na}, "
            f"CLS {p2.get('cls_mobile') or na}, "
            f"INP {p2.get('inp_mobile') or na}"
        )
        cwv_parts = [
            f"LCP {p2.get('cwv_lcp_category') or na}",
            f"CLS {p2.get('cwv_cls_category') or na}",
            f"INP {p2.get('cwv_inp_category') or na}",
        ]
        lines.append(f"  Core Web Vitals field data: {', '.join(cwv_parts)}")
        perf_issues = [
            label for flag, label in [
                (p2.get("render_blocking_resources"), "render-blocking resources"),
                (p2.get("unused_javascript"), "unused JavaScript"),
                (p2.get("unused_css"), "unused CSS"),
            ] if flag
        ]
        if perf_issues:
            lines.append(f"  Performance issues detected: {', '.join(perf_issues)}")
    else:
        lines.append(f"Homepage mobile PSI: not available ({hp_m.get('psi_error') or 'not run'}).")

    if hp_d.get("psi_ran"):
        lines.append(
            f"Homepage desktop: performance {p2.get('performance_score_desktop')}/100, "
            f"LCP {p2.get('lcp_desktop') or na}"
        )

    locale_results = p2.get("locale_psi_results", [])
    if locale_results:
        lines.append(
            f"Locale pages tested: {len(locale_results)}, "
            f"mobile performance range: "
            f"{p2.get('locale_performance_min')}-{p2.get('locale_performance_max')} "
            f"(avg {p2.get('locale_performance_avg')})"
        )
        poor = [r for r in locale_results
                if r.get("performance_score") is not None and r.get("performance_score") < 50]
        if poor:
            lines.append(
                "  Locale pages with poor mobile performance (<50): "
                + ", ".join(f"{r['lang']} ({r.get('performance_score')})" for r in poor)
            )

    lines.append("")

    # ---- Section 3: Homepage Technical Checks ----
    lines.append("## Homepage Technical Checks")
    lines.append(f"- robots.txt: {'present' if p2.get('has_robots_txt') else 'absent'}")
    lines.append(f"- sitemap.xml: {'present' if p2.get('has_sitemap_xml') else 'absent'}")
    lines.append(f"- llms.txt: {'present' if p2.get('has_llms_txt') else 'absent'}")
    lines.append(f"- HSTS header: {'enabled' if p2.get('hsts_present') else 'not detected'}")
    lines.append(f"- HTTP to HTTPS redirect: {'yes' if p2.get('https_redirect') else 'no'}")
    schema_types = p2.get("schema_types", [])
    lines.append(
        f"- Schema.org types: {', '.join(schema_types)}" if schema_types
        else "- Schema.org markup: none detected"
    )
    h1_texts = p2.get("h1_texts", [])
    h1_count = p2.get("h1_count")
    if h1_count is not None:
        h1_str = f"{h1_count} H1 tag(s)"
        if h1_texts:
            h1_str += f" — first: {h1_texts[0]!r}"
        lines.append(f"- Homepage H1: {h1_str}")

    return "\n".join(lines)


def generate_pillar2(facts: dict) -> dict:
    p2 = facts["pillar_2_website_health"]
    company_name = facts["company_name"]
    cf = facts["competitor_facts"]

    p2_facts_str = _format_pillar2_facts(p2)

    # Build competitor rows — no P2 data gathered for competitors
    competitor_rows = "\n".join(
        f'      ["{c.get("company_name", f"Competitor {i+1}")}", '
        f'"Not assessed", "Not assessed", "Not assessed", "Not assessed"]'
        for i, c in enumerate(cf)
    )

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"""
Write Pillar 2: Website Health for {company_name} ({facts['url']}).

CLIENT FACTS - use these exactly, do not change any numbers:
{p2_facts_str}

Write the following sections:
1. pillar_intro: One sentence introducing what this pillar assesses.
2. key_findings_intro: An introductory paragraph (3-4 sentences) using the site health score and performance data to set context. If site health score is available, lead with it.
3. key_findings_bullets: 5-7 bullet points covering the most impactful findings. Prioritize:
   - Site health score (if available) and what it signals about overall technical quality
   - The most critical on-page SEO issues (broken links, missing meta descriptions, missing H1, canonicals) with exact counts
   - Mobile performance score and Core Web Vitals (LCP, CLS) with actual numbers
   - Core Web Vitals field-data status (POOR/NEEDS_IMPROVEMENT/GOOD) if available
   - Thin or duplicate content if significant
   - Technical hygiene (HSTS, schema markup, sitemap, llms.txt, HTTP redirect)
4. impact: Text-only paragraph discussing business impact. No bullet points. Cover: search ranking impact from on-page SEO issues, user experience and bounce rate impact from slow mobile performance, and any crawlability or indexation risks. Be specific to the numbers found.
5. recommendations: Exactly 5 actionable bullet points, ordered by priority.
6. expected_roi: Text-only paragraph with specific ROI percentage ranges tied to the findings (e.g., organic traffic lift from fixing SEO issues, conversion lift from improving LCP).
7. benchmark_table: Columns are Organization, Site Health Score, Mobile Performance, LCP (Mobile), SEO Score (PSI).
   - First row is the client using the exact facts above.
   - Competitor rows use "Not assessed" as no diagnostic tools were run on competitor sites.

Return as JSON:
{{
  "pillar_intro": "...",
  "key_findings_intro": "...",
  "key_findings_bullets": ["...", "..."],
  "impact": "...",
  "recommendations": ["...", "..."],
  "expected_roi": "...",
  "benchmark_table": {{
    "columns": ["Organization", "Site Health Score", "Mobile Performance", "LCP (Mobile)", "SEO Score (PSI)"],
    "rows": [
      ["{company_name}", "...", "...", "...", "..."],
{competitor_rows}
    ]
  }},
  "benchmark_note": "Competitor website health data was not assessed in this audit. A full diagnostic would require running equivalent tools against each competitor site."
}}
"""}
        ]
    )
    return _parse_json(response.choices[0].message.content)


def generate_competitive_landscape(facts: dict, pillar_summaries: dict) -> dict:
    company_name = facts["company_name"]
    cf = facts["competitor_facts"]

    p1_context = pillar_summaries.get("pillar_1", {}).get("key_findings_intro", "")
    p2_context = pillar_summaries.get("pillar_2", {}).get("key_findings_intro", "")
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
    p2 = facts["pillar_2_website_health"]
    p3 = facts["pillar_3_accessibility"]
    p4 = facts["pillar_4_online_reputation"]

    if p2.get("crawl_ran") or p2.get("psi_ran"):
        site_health = (
            f"{p2.get('site_health_score')}/100"
            if p2.get("site_health_score") is not None
            else "N/A"
        )
        mobile_perf = (
            f"{p2.get('performance_score_mobile')}/100"
            if p2.get("performance_score_mobile") is not None
            else "N/A"
        )
        lcp_mobile = p2.get("lcp_mobile") or "N/A"
        p2_health_summary = (
            f"Site health score {site_health}, "
            f"mobile performance {mobile_perf}, "
            f"LCP {lcp_mobile}"
        )
    else:
        p2_health_summary = "not assessed"

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"""
Write the Competitive Landscape section for {company_name} ({facts['url']}).

Client audit summary:
- Globalization: LCR {p1['lcr_score']}% - {p1['lcr_tier']}, {p1['lcr_available']} languages, geographic presence: {p1.get('geographic_presence', 'N/A')}
- Website Health: {p2_health_summary}
- Accessibility: WCAG level {p3.get('wcag_level_claimed', 'undeclared')}, accessibility statement: {'Yes' if p3.get('has_accessibility_statement') else 'No'}, issues: {p3.get('wcag_issues', [])}
- Online Reputation: sentiment {p4.get('overall_sentiment', 'N/A')}, LinkedIn {p4.get('social_media', dict()).get('linkedin', dict()).get('followers', 'N/A')} followers

Already-written pillar summaries for context:
- Globalization: {p1_context}
- Website Health: {p2_context}
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
   - Website Health row: use the client's actual data from above. For competitors, note "Not assessed".

Return as JSON:
{{
  "intro": "...",
  "table": {{
    "headers": ["{company_name}", "{cf[0].get('company_name', 'Competitor 1') if len(cf) > 0 else 'Competitor 1'}", "{cf[1].get('company_name', 'Competitor 2') if len(cf) > 1 else 'Competitor 2'}", "{cf[2].get('company_name', 'Competitor 3') if len(cf) > 2 else 'Competitor 3'}"],
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
    p2_impact = pillar_summaries.get("pillar_2", {}).get("impact", "")
    p3_impact = pillar_summaries.get("pillar_3", {}).get("impact", "")
    p4_impact = pillar_summaries.get("pillar_4", {}).get("impact", "")
    p1_recs = pillar_summaries.get("pillar_1", {}).get("recommendations", [])
    p2_recs = pillar_summaries.get("pillar_2", {}).get("recommendations", [])
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
- Website Health impact: {p2_impact}
- Accessibility impact: {p3_impact}
- Online Reputation impact: {p4_impact}

Already-written pillar recommendations for context:
- Globalization: {p1_recs}
- Website Health: {p2_recs}
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
# Step 5: Generate UI content directly from facts (GPT-5)
# ---------------------------------------------------------------------------

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
        f"sentiment {c.get('overall_sentiment', 'N/A')}, LinkedIn {c.get('linkedin_followers', 'N/A')}"
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

    prompt = f"""You are a senior digital audit expert writing a concise, punchy executive dashboard for a pre-audit report.

Company: {company_name}
Website: {url}

PILLAR 1 - GLOBALIZATION:
- Available languages: {p1.get('available_languages', [])} ({p1.get('lcr_available', 0)} of {p1.get('lcr_required', 0)} required)
- Required languages: {p1.get('required_languages', [])}
- LCR score: {p1.get('lcr_score', 0)}% ({p1.get('lcr_tier', 'N/A')})
- Geographic presence: {p1.get('geographic_presence', 'N/A')}
- Hreflang: {'Present' if p1.get('hreflang_present') else 'Missing'}
- x-default: {'Present' if p1.get('hreflang_x_default_present') else 'Missing'}
- Mixed language issues: {ml_summary}
- Translation quality: {p1.get('translation_quality_notes', 'N/A')}
- Regional/market-specific sites: {p1.get('regional_sites', [])}

PILLAR 2 - WEBSITE HEALTH:
- {psi_summary}
- SEO score (mobile): {p2.get('seo_score_mobile', 'N/A')}, Accessibility score (mobile): {p2.get('accessibility_score_mobile', 'N/A')}
- LCP mobile: {p2.get('lcp_mobile', 'N/A')}, CLS: {p2.get('cls_mobile', 'N/A')}
- Core Web Vitals field data: LCP {p2.get('cwv_lcp_category', 'N/A')}, CLS {p2.get('cwv_cls_category', 'N/A')}, INP {p2.get('cwv_inp_category', 'N/A')}
- Performance issues: render-blocking resources: {p2.get('render_blocking_resources', False)}, unused JavaScript: {p2.get('unused_javascript', False)}, unused CSS: {p2.get('unused_css', False)}
- Pages crawled: {p2.get('pages_crawled', 0)}, broken links: {p2.get('broken_internal_urls', 0)}, missing meta descriptions: {p2.get('missing_meta_descriptions', 0)}
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
- Google Reviews: {p4.get('google_reviews_score', 'N/A')} ({p4.get('google_reviews_count', 'N/A')} reviews)
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

def run_audit(url: str, company_name: str, competitors: list, semrush_pdf_path: str = None) -> dict:
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
            client_crawler = gather_pillar1_facts(url, check_mixed_language=False)
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
        locale_urls = client_crawler.get("locale_urls") if client_crawler else None
        pillar2_data = _gather_p2(url, locale_urls=locale_urls, max_crawl_pages=200)
        print(f"[audit]   Pillar 2 complete. "
              f"PSI ran: {pillar2_data.get('psi_ran')}, "
              f"Crawl ran: {pillar2_data.get('crawl_ran')}, "
              f"Health score: {pillar2_data.get('site_health_score')}")
    except Exception as e:
        print(f"[audit]   Pillar 2 gathering failed: {e}")
        pillar2_data = None

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
        pillar2=pillar2_data,
    )

    # Phase 3: Generate pillar content via GPT-4o (kept for future PDF generation)
    # NOTE: Currently skipped. UI content is generated directly from the facts pack via GPT-5 below.
    # Uncomment this block when PDF generation is added.
    #
    # print("[audit] Generating Pillar 1 (Globalization)...")
    # p1_content = generate_pillar1(facts)
    # print("[audit] Generating Pillar 2 (Website Health)...")
    # p2_content = generate_pillar2(facts)
    # print("[audit] Generating Pillar 3 (Accessibility)...")
    # p3_content = generate_pillar3(facts)
    # print("[audit] Generating Pillar 4 (Online Reputation)...")
    # p4_content = generate_pillar4(facts)
    # pillar_summaries = {"pillar_1": p1_content, "pillar_2": p2_content, "pillar_3": p3_content, "pillar_4": p4_content}
    # print("[audit] Generating Competitive Landscape...")
    # landscape = generate_competitive_landscape(facts, pillar_summaries)
    # print("[audit] Generating Conclusion...")
    # conclusion = generate_conclusion(facts, pillar_summaries)

    # Phase 4: Generate UI content directly from facts pack (GPT-5)
    print("[audit] Generating UI content from facts pack...")
    ui_content = generate_ui_content(facts)

    print("[audit] Done!")

    return {
        "facts": facts,
        "ui_content": ui_content,
    }
