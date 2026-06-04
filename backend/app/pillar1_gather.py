"""
Pillar 1 — Globalization data gathering.

Two public functions:
  gather_pillar1_facts(url, ...)        — Playwright crawler: locale URLs, hreflang, selector type
  gather_mixed_language_issues(domain, available_languages) — GPT-5: find mixed-language UX issues
"""

import json
import os
import re

try:
    from app.log_ctx import plog
except ImportError:
    from log_ctx import plog
from urllib.parse import urlparse
from typing import Dict, Optional

from openai import OpenAI

try:
    import tldextract as _tldextract
    _TLDEXTRACT_AVAILABLE = True
except ImportError:
    _TLDEXTRACT_AVAILABLE = False

openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


COMMON_LANG_CODES = {
    "AR", "BG", "CS", "DA", "DE", "EL", "EN", "ES", "ET", "FA", "FI", "FR",
    "HE", "HI", "HR", "HU", "ID", "IT", "JA", "KO", "LT", "LV", "MS", "NL",
    "NO", "PL", "PT", "RO", "RU", "SK", "SL", "SR", "SV", "TH", "TR", "UK",
    "VI", "ZH",
}

# Genuine language variants where region changes translation content (not geo-routing).
# Only these are preserved as distinct entries in available_languages.
KNOWN_LANGUAGE_VARIANTS = {
    "ZH-CN", "ZH-TW", "ZH-HK",
    "PT-BR", "PT-PT",
    "FR-CA",
    "EN-GB", "EN-US", "EN-AU",
    "ES-MX", "ES-ES",
    "NB-NO", "NN-NO",
    "SR-LATN", "SR-CYRL",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_lang(raw: str) -> str:
    return re.split(r'[-_]', raw)[0].upper()


def _is_probable_lang_code(code: str) -> bool:
    return bool(code and re.fullmatch(r"[A-Z]{2}", code) and code in COMMON_LANG_CODES)


def _add_locale_candidate(locale_urls: dict, code: Optional[str], href: Optional[str]) -> None:
    if not code or not href:
        return
    clean = code.upper()
    if clean == "X-DEFAULT":
        return
    if clean not in locale_urls:
        locale_urls[clean] = href


def _extract_code_from_href(href: str, base_url: str) -> Optional[str]:
    if not href:
        return None

    query_match = re.search(
        r"[?&](?:lang|locale|hl|language)=([a-z]{2}(?:[-_][a-z]{2})?)(?:[&#]|$)",
        href, re.IGNORECASE,
    )
    if query_match:
        code = _normalize_lang(query_match.group(1))
        if _is_probable_lang_code(code):
            return code

    hash_match = re.search(
        r"#(?:/|.*(?:lang|locale)=)([a-z]{2}(?:[-_][a-z]{2})?)(?:[&#/]|$)",
        href, re.IGNORECASE,
    )
    if hash_match:
        code = _normalize_lang(hash_match.group(1))
        if _is_probable_lang_code(code):
            return code

    path_match = re.search(r"/(?:[a-z]{2}(?:[-_][a-z]{2})?)(?:/|$|\?)", href, re.IGNORECASE)
    if path_match:
        code = _normalize_lang(path_match.group(0).strip("/?"))
        if _is_probable_lang_code(code):
            return code

    try:
        if _TLDEXTRACT_AVAILABLE:
            ext_href = _tldextract.extract(href)
            ext_base = _tldextract.extract(base_url)
            if (
                ext_href.registered_domain
                and ext_href.registered_domain == ext_base.registered_domain
                and ext_href.subdomain
            ):
                sub = ext_href.subdomain.split(".")[0]
                if re.fullmatch(r"[a-z]{2}(?:[-_][a-z]{2})?", sub, re.IGNORECASE):
                    code = _normalize_lang(sub)
                    if _is_probable_lang_code(code):
                        return code
        else:
            parsed_href = urlparse(href)
            parsed_base = urlparse(base_url)
            host = (parsed_href.hostname or "").lower().removeprefix("www.")
            base_host = (parsed_base.hostname or "").lower().removeprefix("www.")
            host_parts = host.split(".")
            base_parts = base_host.split(".")
            if len(host_parts) >= 3 and len(base_parts) >= 2:
                if ".".join(host_parts[-2:]) == ".".join(base_parts[-2:]):
                    sub = host_parts[0]
                    if re.fullmatch(r"[a-z]{2}(?:[-_][a-z]{2})?", sub, re.IGNORECASE):
                        code = _normalize_lang(sub)
                        if _is_probable_lang_code(code):
                            return code
    except Exception:
        return None

    return None


def _detect_locale_urls(page, base_url: str) -> dict:
    locale_urls = {}

    hreflang_tags = page.evaluate("""() => {
        return Array.from(
            document.querySelectorAll('link[rel="alternate"][hreflang]')
        ).map(el => ({ lang: el.hreflang, href: el.href }));
    }""")

    for tag in hreflang_tags:
        lang = tag.get("lang", "")
        href = tag.get("href", "")
        if lang and href and lang.lower() != "x-default":
            full_code = lang.replace("_", "-").upper()
            code = full_code if full_code in KNOWN_LANGUAGE_VARIANTS else _normalize_lang(lang)
            _add_locale_candidate(locale_urls, code, href)

    switcher_links = page.evaluate("""() => {
        const selectors = [
            '.lang-switcher a', '.language-switcher a', '.language-selector a',
            '.lang-selector a', '.languages a', '#lang-switcher a',
            '[class*="lang"] a', '[class*="language"] a',
            '[id*="lang"] a', '[id*="language"] a',
            'header a[hreflang]', 'nav a[hreflang]',
        ];
        const found = [];
        for (const sel of selectors) {
            try {
                document.querySelectorAll(sel).forEach(el => {
                    const href = el.href;
                    const text = (el.innerText || el.textContent || '').trim();
                    const lang = el.getAttribute('hreflang') || el.getAttribute('lang') || '';
                    if (href) found.push({ href, text, lang });
                });
            } catch(e) {}
        }
        return found;
    }""")

    for link in switcher_links:
        href = link.get("href", "")
        text = link.get("text", "").strip()
        lang_attr = link.get("lang", "")

        code = None
        if lang_attr:
            code = _normalize_lang(lang_attr)
        elif re.match(r'^[A-Za-z]{2}(-[A-Za-z]{2})?$', text):
            code = text[:2].upper()
        else:
            code = _extract_code_from_href(href, base_url)

        if code and not _is_probable_lang_code(code):
            code = None

        _add_locale_candidate(locale_urls, code, href)

    broad_links = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('a[href]')).map(el => ({
            href: el.href || '',
            text: (el.innerText || el.textContent || '').trim(),
            lang: el.getAttribute('hreflang') || el.getAttribute('lang') || '',
        }));
    }""")

    for link in broad_links:
        href = link.get("href", "")
        lang_attr = link.get("lang", "")
        text = link.get("text", "")

        code = None
        if lang_attr:
            code = _normalize_lang(lang_attr)
        elif re.match(r'^[A-Za-z]{2}(-[A-Za-z]{2})?$', text):
            code = text[:2].upper()
        else:
            code = _extract_code_from_href(href, base_url)

        if code and _is_probable_lang_code(code):
            _add_locale_candidate(locale_urls, code, href)

    return locale_urls


def _detect_cookie_banner(page) -> dict:
    """
    Detect cookie consent banners and identify the CMP provider.
    Uses two strategies:
      1. Script/style signals — reliable because they're in the HTML source
         (CMP scripts are loaded server-side, so their tags are always present)
      2. DOM element signals — for banners that are already rendered
    Returns {"detected": bool, "provider": str | None}
    """
    result = page.evaluate("""() => {
        // --- Strategy 1: script/style tag signals (always present in source) ---
        const scriptSignals = [
            { name: "Cookiebot",  patterns: ["consent.cookiebot.com", "cookiebot.com/uc.js", "cookiebot.com/cc.js"] },
            { name: "OneTrust",   patterns: ["cdn.cookielaw.org", "optanon.blob.core.windows.net"] },
            { name: "Didomi",     patterns: ["sdk.privacy-center.org", "didomi.io"] },
            { name: "TrustArc",   patterns: ["consent.trustarc.com", "trustarc.com/notice"] },
            { name: "CookieYes",  patterns: ["cdn-cookieyes.com", "app.cookieyes.com"] },
            { name: "Osano",        patterns: ["cmp.osano.com"] },
            { name: "Axeptio",      patterns: ["static.axept.io"] },
            { name: "Iubenda",      patterns: ["cdn.iubenda.com/cs/iubenda_cs.js"] },
            { name: "Quantcast",    patterns: ["cmp.quantcast.com"] },
            { name: "Usercentrics",   patterns: ["app.usercentrics.eu", "privacy-proxy.usercentrics.eu"] },
            { name: "Termly",         patterns: ["app.termly.io"] },
            { name: "CookieScript",   patterns: ["cookiescriptcdn.pro", "cookie-script.com"] },
            { name: "CookieInfo",     patterns: ["policy.app.cookieinformation.com", "cookieinformation.com"] },
            { name: "Complianz",      patterns: ["cdn.complianz.io", "complianz.io"] },
            { name: "CookieFirst",    patterns: ["consent.cookiefirst.com", "cookiefirst.com"] },
            { name: "Consentmanager", patterns: ["cdn.consentmanager.net", "consentmanager.net"] },
            { name: "Pandectes",      patterns: ["pandectes.io"] },
            { name: "Sourcepoint",    patterns: ["sourcepoint.com", "sp-prod.net", "cdn.privacy-mgmt.com"] },
            { name: "Civic",          patterns: ["cc.cdn.civiccomputing.com", "cookiecontrol.civiccomputing.com"] },
            { name: "PiwikPRO",       patterns: ["piwik.pro"] },
        ];
        const allScripts = Array.from(document.querySelectorAll('script[src]')).map(s => s.src || '');
        for (const sig of scriptSignals) {
            for (const pattern of sig.patterns) {
                if (allScripts.some(src => src.includes(pattern))) {
                    return { detected: true, provider: sig.name };
                }
            }
        }

        // TrustArc newer UI: branding image loaded from consent.trustarc.com (no script tag)
        const allImgSrcs = Array.from(document.querySelectorAll('img[src]')).map(s => s.src || '');
        if (allImgSrcs.some(src => src.includes('consent.trustarc.com'))) {
            return { detected: true, provider: 'TrustArc' };
        }

        // Check script id attributes (e.g. <script id="Cookiebot">)
        const scriptIdSignals = [
            { name: "Cookiebot",  ids: ["Cookiebot", "cookiebot"] },
            { name: "OneTrust",   ids: ["onetrust-script", "OptanonWrapper"] },
        ];
        for (const sig of scriptIdSignals) {
            for (const id of sig.ids) {
                if (document.getElementById(id)) {
                    return { detected: true, provider: sig.name };
                }
            }
        }

        // Check style tag IDs injected by CMPs (present even before dialog renders)
        const styleIdSignals = [
            { name: "Cookiebot",  ids: ["CookiebotDialogStyle", "CookieConsentStateDisplayStyles"] },
            { name: "OneTrust",   ids: ["onetrust-style"] },
        ];
        for (const sig of styleIdSignals) {
            for (const id of sig.ids) {
                if (document.getElementById(id)) {
                    return { detected: true, provider: sig.name };
                }
            }
        }

        // Check window globals set by CMP scripts
        const windowSignals = [
            { name: "Cookiebot",  globals: ["Cookiebot", "CookieConsentDialog"] },
            { name: "OneTrust",   globals: ["OneTrust", "OptanonWrapper"] },
            { name: "Didomi",         globals: ["Didomi", "__tcfapi"] },
            { name: "Usercentrics",   globals: ["UC_UI", "usercentrics"] },
            { name: "Termly",         globals: ["termly"] },
            { name: "CookieScript",   globals: ["CookieScript"] },
            { name: "CookieInfo",     globals: ["CookieInformation"] },
            { name: "Sourcepoint",    globals: ["_sp_"] },
            { name: "Civic",          globals: ["CookieControl"] },
            { name: "PiwikPRO",       globals: ["ppms"] },
            { name: "Consentmanager", globals: ["cmp_id"] },
        ];
        for (const sig of windowSignals) {
            for (const g of sig.globals) {
                if (window[g] !== undefined) {
                    return { detected: true, provider: sig.name };
                }
            }
        }

        // Tealium consent — utag is common as a tag manager, so check utag.gdpr specifically
        if (window.utag && window.utag.gdpr !== undefined) {
            return { detected: true, provider: "Tealium" };
        }

        // --- Strategy 2: rendered DOM elements ---
        const domProviders = [
            { name: "OneTrust",   selectors: ["#onetrust-banner-sdk", ".onetrust-pc-dark-filter"] },
            { name: "Cookiebot",  selectors: ["#CybotCookiebotDialog", "[data-cookieconsent]"] },
            { name: "Didomi",     selectors: ["#didomi-host", ".didomi-popup-container"] },
            { name: "TrustArc",   selectors: ["#truste-consent-track", ".truste_overlay", ".pdynamicbutton"] },
            { name: "CookieYes",  selectors: [".cky-consent-container", "#cky-consent"] },
            { name: "Osano",      selectors: [".osano-cm-window", ".osano-cm-widget"] },
            { name: "Axeptio",    selectors: ["#axeptio_overlay"] },
            { name: "Iubenda",    selectors: ["#iubenda-cs-banner"] },
            { name: "Quantcast",    selectors: [".qc-cmp2-container"] },
            { name: "Usercentrics",   selectors: ["#usercentrics-root", "[data-testid='uc-banner']"] },
            { name: "Termly",         selectors: ["#termly-code-snippet-support", ".termly-styles-wrapper"] },
            { name: "CookieScript",   selectors: ["#cookiescript_injected", ".cookiescript-banner"] },
            { name: "CookieInfo",     selectors: ["#coiOverlay", ".coi-banner__wrapper"] },
            { name: "Complianz",      selectors: [".cmplz-cookiebanner", "#cmplz-cookiebanner-container"] },
            { name: "CookieFirst",    selectors: ["[data-cookiefirst-root]", "#cookiefirst-cookies-consent"] },
            { name: "Consentmanager", selectors: ["#cmpbox", ".cmpbox"] },
            { name: "Pandectes",      selectors: [".pandectes-banner", "#pandectes-banner"] },
            { name: "Sourcepoint",    selectors: ["[id^='sp_message_container']", ".sp_choice_type_ACCEPT_ALL"] },
            { name: "Civic",          selectors: ["#ccc", "#ccc-module"] },
            { name: "PiwikPRO",       selectors: ["#ppms_cm_popup_overlay", ".ppms_cm_popup"] },
        ];
        for (const provider of domProviders) {
            for (const sel of provider.selectors) {
                try {
                    if (document.querySelector(sel)) return { detected: true, provider: provider.name };
                } catch(e) {}
            }
        }

        // Generic fallback
        const genericSelectors = [
            "[id*='cookie'][id*='banner']", "[id*='cookie'][id*='consent']",
            "[class*='cookie'][class*='banner']", "[class*='cookie'][class*='consent']",
            "[class*='consent'][class*='banner']", "[id*='gdpr']", "[class*='gdpr']",
        ];
        for (const sel of genericSelectors) {
            try {
                if (document.querySelector(sel)) return { detected: true, provider: null };
            } catch(e) {}
        }

        return { detected: false, provider: null };
    }""")
    return result


def _detect_language_selector_type(page) -> str:
    result = page.evaluate("""() => {
        if (document.querySelector('select option[lang], select[id*="lang"], select[class*="lang"]'))
            return 'dropdown';
        const flagImgs = document.querySelectorAll(
            '[class*="lang"] img, [class*="language"] img, [id*="lang"] img'
        );
        if (flagImgs.length > 0) return 'dropdown with flags';
        const langLinks = document.querySelectorAll(
            '[class*="lang"] a, [class*="language"] a'
        );
        if (langLinks.length > 0) return 'text links';
        return 'unknown';
    }""")
    return result


# ---------------------------------------------------------------------------
# Public function 1 — Playwright crawler
# ---------------------------------------------------------------------------

def gather_pillar1_facts(url: str) -> dict:
    """
    Load the client's website with a headless browser and extract:
      - Available locale URLs (from hreflang or language switcher)
      - Whether hreflang tags are present
      - Language selector type
      - Cookie banner presence and provider
    """
    result = {
        "available_languages": [],
        "available_language_variants": [],
        "language_selector_type": "unknown",
        "locale_urls": {},
        "hreflang_tags": [],
        "hreflang_present": False,
        "hreflang_x_default_present": False,
        "hreflang_x_default_url": None,
        "mixed_language_issues": [],
        "pages_checked": 0,
        "crawler_ran": False,
        "crawler_error": None,
        "target_languages": [],
        "cookie_banner_detected": False,
        "cookie_provider": None,
    }

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(15000)

            plog(f"[crawler] Loading {url} ...")
            try:
                page.goto(url, wait_until="domcontentloaded")
            except Exception as nav_err:
                if "ERR_HTTP2_PROTOCOL_ERROR" in str(nav_err):
                    plog(f"[crawler] HTTP/2 error, retrying with HTTP/1.1...")
                    browser.close()
                    browser = p.chromium.launch(headless=True, args=["--disable-http2"])
                    page = browser.new_page()
                    page.set_default_timeout(15000)
                    page.goto(url, wait_until="domcontentloaded")
                else:
                    raise

            # Wait for hreflang tags to appear — JS frameworks (e.g. Next.js) may inject
            # them after domcontentloaded, so reading immediately can return 0 tags.
            try:
                page.wait_for_selector('link[rel="alternate"][hreflang]', timeout=5000)
            except Exception:
                # Site has no hreflang tags, or they didn't load in time.
                # Give JS-rendered locales a bit more time before locale detection.
                page.wait_for_timeout(3000)

            raw_hreflang = page.evaluate("""() => {
                return Array.from(
                    document.querySelectorAll('link[rel="alternate"][hreflang]')
                ).map(el => ({ lang: el.hreflang.toLowerCase(), href: el.href }));
            }""")
            result["hreflang_tags"] = raw_hreflang
            result["hreflang_present"] = len(raw_hreflang) > 0
            x_default = next((t for t in raw_hreflang if t.get("lang") == "x-default"), None)
            result["hreflang_x_default_present"] = x_default is not None
            result["hreflang_x_default_url"] = x_default.get("href") if x_default else None

            variant_set = {
                str(t.get("lang", "")).replace("_", "-").upper()
                for t in raw_hreflang
                if t.get("lang") and str(t.get("lang")).lower() != "x-default"
            }

            locale_urls = _detect_locale_urls(page, url)

            html_lang = page.evaluate("""() => {
                return document.documentElement.lang
                    || document.querySelector('meta[property="og:locale"]')?.getAttribute('content')
                    || '';
            }""")
            plog(f"[crawler] Homepage lang signal: {html_lang!r}")
            if html_lang:
                base_code = _normalize_lang(html_lang)
                if _is_probable_lang_code(base_code) and base_code not in locale_urls:
                    locale_urls[base_code] = url
                    plog(f"[crawler] Added base language {base_code} from html/og:locale")

                html_variant = str(html_lang).replace("_", "-").upper()
                if html_variant and html_variant != "X-DEFAULT":
                    variant_set.add(html_variant)

            result["locale_urls"] = locale_urls
            result["available_languages"] = sorted(locale_urls.keys())
            result["available_language_variants"] = (
                sorted(variant_set) if variant_set else sorted(locale_urls.keys())
            )
            result["language_selector_type"] = _detect_language_selector_type(page)

            # Give GTM-injected CMPs time to fire before checking the DOM.
            # Sites that load their CMP via GTM rather than a direct script tag
            # need a brief pause — without this they always appear as "no banner".
            page.wait_for_timeout(10000)

            cookie_info = _detect_cookie_banner(page)
            result["cookie_banner_detected"] = cookie_info.get("detected", False)
            result["cookie_provider"] = cookie_info.get("provider")
            plog(f"[crawler] Cookie banner: {result['cookie_banner_detected']} (provider: {result['cookie_provider']})")

            plog(f"[crawler] Found {len(locale_urls)} locales: {list(locale_urls.keys())}")

            browser.close()
            result["crawler_ran"] = True
            plog(f"[crawler] Pillar 1 crawl complete. "
                  f"{result['pages_checked']} pages checked, "
                  f"{len(result['mixed_language_issues'])} locales with mixed-language markers.")

    except Exception as e:
        result["crawler_error"] = str(e)
        plog(f"[crawler] ERROR: {e}")

    return result


# ---------------------------------------------------------------------------
# Public function 2 — GPT-5 mixed language detection
# ---------------------------------------------------------------------------

def _flatten_mixed_language_issues(issues: list) -> list:
    """
    Rescue locale issue objects that GPT nested inside language_hits instead of
    placing at the top level. Detection rule: any language_hits item that contains
    a 'locale' key is a misplaced locale issue, not a real language hit.
    """
    result = []
    for issue in issues:
        real_hits = []
        rescued = []
        for hit in issue.get('language_hits', []):
            if 'locale' in hit:
                # Merged case: hit has both language/marker_strings AND locale properties
                if hit.get('language') and hit.get('marker_strings_found'):
                    real_hits.append({
                        'language': hit['language'],
                        'marker_strings_found': hit['marker_strings_found'],
                    })
                rescued.append({
                    'locale': hit['locale'],
                    'page_url': hit.get('page_url', ''),
                    'language_hits': [
                        h for h in hit.get('language_hits', [])
                        if h.get('language') and h.get('marker_strings_found')
                    ],
                })
            elif hit.get('language') and hit.get('marker_strings_found'):
                real_hits.append(hit)
        result.append({**issue, 'language_hits': real_hits})
        result.extend(rescued)
    return result


def gather_mixed_language_issues(domain: str, locale_urls: dict) -> list:
    """
    Use GPT-5 with web search to find mixed-language UX issues on the site.

    More thorough than string-based detection — catches any language bleeding
    into the wrong locale, not just French. GPT is given the exact locale URLs
    discovered by the crawler so it checks known pages rather than guessing.

    locale_urls: dict of {lang_code: url} from gather_pillar1_facts()
      e.g. {"EN": "https://example.com/en/", "FR": "https://example.com/fr/"}

    Returns a list of issue dicts matching the crawler's mixed_language_issues format:
      [{"locale": "EN", "page_url": "...", "language_hits": [{"language": "FR", "marker_strings_found": [...]}]}]
    Returns [] if no issues found or if the call fails.
    """
    if not locale_urls:
        return []

    locale_lines = "\n".join(
        f"  - {lang}: {url}" for lang, url in locale_urls.items()
    )

    prompt = f"""
You are auditing the website {domain} for mixed-language UX issues.

The crawler has confirmed the following locale pages exist. Visit each one:
{locale_lines}

A mixed-language issue is when a locale page (e.g. the English version) displays
text in a different language — for example, a French CTA like "En savoir plus" or
a German nav label on an English page. This is a localization quality problem.

For each locale URL above:
1. Visit the exact URL provided
2. Identify any visible UI text (buttons, CTAs, navigation labels, headings,
   card links, form labels) that appears to be in the wrong language for that locale
3. Quote the specific strings you found

Only report genuine cross-language contamination. Ignore:
- Brand names, product names, proper nouns, or fashion terms.
- Technical strings (URLs, email addresses, code)
- Content intentionally in another language (e.g. a quote or language-learning site)
- Language switcher labels — names of languages like "English", "Français", "Deutsch" appearing in navigation or a language picker are always intentional and must never be flagged

Return a flat JSON array — one object per locale at the top level.
Never nest locale objects inside language_hits.
language_hits must only contain objects with "language" and "marker_strings_found" keys — nothing else.
Return an empty array if no issues are found. No markdown fences.

[
  {{
    "locale": "EN",
    "page_url": "https://example.com/en/",
    "language_hits": [
      {{
        "language": "FR",
        "marker_strings_found": ["actual string found on page", "another string found"]
      }}
    ]
  }},
  {{
    "locale": "DE",
    "page_url": "https://example.com/de/",
    "language_hits": [
      {{
        "language": "EN",
        "marker_strings_found": ["actual english string found on german page"]
      }},
      {{
        "language": "FR",
        "marker_strings_found": ["actual french string found on german page"]
      }}
    ]
  }}
]
"""
    try:
        resp = openai_client.responses.create(
            model="gpt-5",
            tools=[{"type": "web_search"}],
            input=prompt,
        )
        usage = getattr(resp, "usage", None)
        if usage:
            plog(
                f"[pillar1 mixed-lang tokens] "
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
            try:
                from json_repair import repair_json
                result = json.loads(repair_json(clean))
                plog("  [json_repair] Recovered mixed-language JSON.")
            except Exception:
                match = re.search(r'\[.*\]', clean, re.DOTALL)
                if match:
                    try:
                        result = json.loads(match.group())
                    except json.JSONDecodeError:
                        return []
                else:
                    return []
        if not isinstance(result, list):
            return []
        result = _flatten_mixed_language_issues(result)
        return [
            item for item in result
            if (
                isinstance(item, dict)
                and isinstance(item.get("locale"), str)
                and isinstance(item.get("page_url"), str)
                and isinstance(item.get("language_hits"), list)
                and len(item["language_hits"]) > 0
            )
        ]
    except Exception as e:
        plog(f"  [warn] gather_mixed_language_issues failed: {e}")
        return []
