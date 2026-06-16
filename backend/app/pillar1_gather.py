"""
Pillar 1 — Globalization data gathering.

Two public functions:
  gather_pillar1_facts(url, ...) - Launches a Playwright crawler, curl request and sitemap crawl in parallel for locale URLs, hreflang, selector type
  gather_mixed_language_issues(domain, available_languages) — GPT-5: find mixed-language UX issues
"""

import gzip
import json
import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

try:
    from app.log_ctx import plog
except ImportError:
    from log_ctx import plog
from urllib.parse import urlparse
from typing import Optional

from openai import OpenAI

try:
    import tldextract as _tldextract
    _TLDEXTRACT_AVAILABLE = True
except ImportError:
    _TLDEXTRACT_AVAILABLE = False

try:
    from curl_cffi import requests as _creq
    _CURL_CFFI_AVAILABLE = True
except ImportError:
    _CURL_CFFI_AVAILABLE = False

try:
    from bs4 import BeautifulSoup as _BS
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False

_CURL_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
_SITEMAP_XHTML_NS = "http://www.w3.org/1999/xhtml"

openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Standard 2-letter language codes commonly used in locales, for quick validation of extracted codes.
COMMON_LANG_CODES = {
    "AF", "AR", "AZ", "BE", "BG", "BN", "CA", "CS", "CY", "DA", "DE", "EL",
    "EN", "ES", "ET", "FA", "FI", "FR", "GL", "HE", "HI", "HR", "HT", "HU",
    "ID", "IS", "IT", "JA", "KA", "KK", "KO", "LT", "LV", "MK", "MN", "MS",
    "MY", "NE", "NL", "NO", "PL", "PT", "RO", "RU", "SK", "SL", "SQ", "SR",
    "SV", "SW", "TA", "TH", "TL", "TR", "UK", "UR", "VI", "ZH",
}

# Genuine language variants where region changes translation content. Only these are preserved as distinct entries in available_languages.
KNOWN_LANGUAGE_VARIANTS = {
    "ZH-CN", "ZH-TW", "ZH-HK",
    "PT-BR", "PT-PT",
    "FR-CA",
    "ES-MX", "ES-ES",
    "NB-NO", "NN-NO",
    "SR-LATN", "SR-CYRL",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Native language names that won't match the 2-letter ISO code regex (kinda annoying to hardcode, but at least sometwhat helpful)
_LANG_NAME_TO_CODE: dict[str, str] = {
    "česky": "CS", "čeština": "CS",
    "日本語": "JA",
    "한국어": "KO",
    "中文": "ZH", "简体中文": "ZH", "繁體中文": "ZH",
    "ελληνικά": "EL",
    "українська": "UK",
    "dansk": "DA",
    "svenska": "SV",
    "norsk": "NO",
    "suomi": "FI",
    "slovenčina": "SK",
    "slovenščina": "SL",
    "hrvatski": "HR",
    "български": "BG",
    "română": "RO",
    "magyar": "HU",
    "العربية": "AR",
    "עברית": "HE",
    "ภาษาไทย": "TH",
    "tiếng việt": "VI",
}


def _normalize_lang(raw: str) -> str:
    """Split delimiters, uppercase, and return base language code."""
    return re.split(r'[-_]', raw)[0].upper()


def _is_probable_lang_code(code: str) -> bool:
    """Heuristic check to filter out clearly invalid language codes. Not perfect but helps reduce noise from false positives."""
    return bool(code and re.fullmatch(r"[A-Z]{2}", code) and code in COMMON_LANG_CODES)


def _add_locale_candidate(locale_urls: dict, code: Optional[str], href: Optional[str]) -> None:
    """Add a locale candidate to the locale_urls dict if it has a valid code and href, and we don't already have an entry for that code. X-DEFAULT is ignored since it's not a real language."""
    if not code or not href:
        return
    clean = code.upper()
    if clean == "X-DEFAULT":
        return
    if clean not in locale_urls:
        locale_urls[clean] = href


def _extract_code_from_href(href: str, base_url: str) -> Optional[str]:
    """Try to extract a language code from the URL using multiple strategies:"""

    # ignore if not href
    if not href:
        return None

    # Check for language code in query parameters, and return if seems valid
    query_match = re.search(
        r"[?&](?:lang|locale|hl|language)=([a-z]{2}(?:[-_][a-z]{2})?)(?:[&#]|$)",
        href, re.IGNORECASE,
    )
    if query_match:
        code = _normalize_lang(query_match.group(1))
        if _is_probable_lang_code(code):
            return code

    # Check for language code in url hash fragment (eg. #/en/)
    hash_match = re.search(
        r"#(?:/|.*(?:lang|locale)=)([a-z]{2}(?:[-_][a-z]{2})?)(?:[&#/]|$)",
        href, re.IGNORECASE,
    )
    if hash_match:
        code = _normalize_lang(hash_match.group(1))
        if _is_probable_lang_code(code):
            return code

    # Check for code in path segements
    path_segments = [s for s in urlparse(href).path.split("/") if s][:3]
    for i, seg in enumerate(path_segments):
        if re.fullmatch(r"[a-z]{2}(?:[-_][a-z]{2,4})?", seg, re.IGNORECASE):
            code = _normalize_lang(seg)
            if _is_probable_lang_code(code):
                # Country-first URLs (/nl/en/, /it/en/): if the next segment is also
                # a lang code, prefer it, the first is a country code, second is likely language.
                if i + 1 < len(path_segments):
                    next_seg = path_segments[i + 1]
                    if re.fullmatch(r"[a-z]{2}(?:[-_][a-z]{2,4})?", next_seg, re.IGNORECASE):
                        next_code = _normalize_lang(next_seg)
                        if _is_probable_lang_code(next_code):
                            return next_code
                return code

    try:
        # extract subdomain and check if it's a language code only if the registered domain matches the base URL's registered domain
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
            # manual parsing, but hopefully will not be used. 
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

    # try to check hreflang tags first, since they're the clearest signal
    hreflang_tags = page.evaluate("""() => {
        return Array.from(
            document.querySelectorAll('link[rel="alternate"][hreflang]')
        ).map(el => ({ lang: el.hreflang, href: el.href }));
    }""")

    # map lang codes to urls if they're valid languages
    for tag in hreflang_tags:
        lang = tag.get("lang", "")
        href = tag.get("href", "")
        if lang and href and lang.lower() != "x-default":
            code = _normalize_lang(lang)
            if _is_probable_lang_code(code):
                _add_locale_candidate(locale_urls, code, href)

    # check to see if there are any langauge switchers that link to other urls. Returns array of urls with corresponding langs
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

    # Determine language code for each switcher link
    for link in switcher_links:
        href = link.get("href", "")
        text = link.get("text", "").strip()
        lang_attr = link.get("lang", "")

        code = None
        if lang_attr:
            code = _normalize_lang(lang_attr)
        elif re.match(r'^[A-Za-z]{2}(-[A-Za-z]{2})?$', text):
            code = text[:2].upper()
        elif _LANG_NAME_TO_CODE.get(text.lower()):
            code = _LANG_NAME_TO_CODE[text.lower()]
        else:
            code = _extract_code_from_href(href, base_url)

        if code and not _is_probable_lang_code(code):
            code = None

        _add_locale_candidate(locale_urls, code, href)


    # check all <a> tags available on the site
    broad_links = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('a[href]')).map(el => ({
            href: el.href || '',
            text: (el.innerText || el.textContent || '').trim(),
            lang: el.getAttribute('hreflang') || el.getAttribute('lang') || '',
        }));
    }""")

    _SOCIAL_DOMAINS = {
        "instagram.com", "facebook.com", "twitter.com", "x.com", "linkedin.com",
        "youtube.com", "tiktok.com", "pinterest.com", "snapchat.com", "reddit.com",
        "whatsapp.com", "telegram.org", "discord.com", "twitch.tv",
    }

    for link in broad_links:
        href = link.get("href", "")
        lang_attr = link.get("lang", "")
        text = link.get("text", "")

        # Skip social media links — they use ?hl= for their own UI language, not site locale.
        if href:
            href_host = (urlparse(href).hostname or "").lower().removeprefix("www.")
            if any(href_host == d or href_host.endswith("." + d) for d in _SOCIAL_DOMAINS):
                continue

        # if theres a lang attr, use it. Otherwise match text fo the link, and lastly heck href
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
      1. Script/style signals, which are reliable because they're in the HTML source
      2. DOM element signals for banners that are already rendered
    Returns {"detected": bool, "provider": str | None}
    """

    # Check the script tags for known domains. For known cookie providers, we can look for standard attributes
    result = page.evaluate("""() => {
        // Strategy 1: script/style tag signals 
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
            { name: "Cookieconsent",  patterns: ["cookieconsent.min.js", "cookieconsent.js", "/cookieconsent/"] },
            { name: "Tarteaucitron",  patterns: ["tarteaucitron.js", "tarteaucitron.min.js", "tarteaucitron.io"] },
            { name: "Klaro",          patterns: ["klaro.js", "kiprotect.com/klaro"] },
            { name: "Borlabs",        patterns: ["borlabs-cookie/js/", "borlabs-cookie.min.js"] },
            { name: "SFBX",           patterns: ["sfbx.com", "consenso.sfbx.com"] },
            { name: "CCM19",          patterns: ["cdn.ccm19.de", "ccm19.de"] },
            { name: "Cookiehub",      patterns: ["cookiehub.com"] },
            { name: "TrustCommander", patterns: ["tagcommander.com", "commander1.com"] },
            { name: "Webcare",        patterns: ["webcare.io"] },
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

        // Strategy 2: rendered DOM elements
        const domProviders = [
            { name: "OneTrust",   selectors: ["#onetrust-banner-sdk", ".onetrust-pc-dark-filter", ".ot-sdk-container", "#onetrust-group-container", "#onetrust-accept-btn-handler", "#onetrust-policy"] },
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
            { name: "Tarteaucitron",  selectors: ["#tarteaucitronAlertBig", "#tarteaucitron", ".tarteaucitronAlertBig"] },
            { name: "Klaro",          selectors: [".klaro", ".cm-app-container", "#klaro"] },
            { name: "Borlabs",        selectors: ["#BorlabsCookieBox", ".BorlabsCookie"] },
            { name: "SFBX",           selectors: ["#sfbx-consent", ".sfbx-consent"] },
            { name: "CCM19",          selectors: [".ccm-widget", "#ccm19-cn", ".ccm19-overlay"] },
            { name: "Cookiehub",      selectors: ["#ch2", ".ch2-dialog", "#cookiehub"] },
            { name: "TrustCommander", selectors: ["#tc-privacy-button", ".tc-privacy-wrapper"] },
            { name: "Webcare",        selectors: [".webcare-popup", "#webcare-cookie-consent"] },
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
    """Checks for lang selector type. This could be a dropdown, dropdown with flags, or text links. Default to unknown."""
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


def _detect_translation_plugin(page) -> dict:
    """
    Detect machine-translation overlay plugins (GTranslate, Weglot, Google Translate widget).
    Returns {"plugin": str | None, "languages": [str]} where languages are uppercase ISO codes
    extracted from the plugin's flag widget (if available).
    """
    return page.evaluate("""() => {
        const scripts = Array.from(document.scripts).map(s => s.src || '');

        // GTranslate: DOM class is the primary signal
        // (e.g. ExactDN) with no gtranslate.net hostname, but the path always contains /plugins/gtranslate/.
        const hasGTranslate = !!document.querySelector('.gt_switcher, [id^="gt-wrapper-"]')
            || scripts.some(s => s.includes('gtranslate.net') || s.includes('/plugins/gtranslate/'));
        if (hasGTranslate) {
            // data-gt-lang is canonical and present on every switcher link across all GTranslate installs
            const langs = [...new Set(
                Array.from(document.querySelectorAll('a[data-gt-lang]'))
                    .map(a => (a.getAttribute('data-gt-lang') || '').trim())
                    .filter(v => /^[a-z]{2}(-[a-z]{2,4})?$/i.test(v))
            )];
            return { plugin: 'gtranslate', languages: langs };
        }

        if (scripts.some(s => s.includes('cdn.weglot.com'))) {
            return { plugin: 'weglot', languages: [] };
        }

        // Standalone Google Translate widget (not via GTranslate plugin)
        if (scripts.some(s => s.includes('translate.google.com/translate_a/element')
                || s.includes('translate.googleapis.com/translate_a/element'))) {
            return { plugin: 'google-translate', languages: [] };
        }

        return { plugin: null, languages: [] };
    }""")


# ---------------------------------------------------------------------------
# Leg 1: curl_cffi raw HTML fetch
# ---------------------------------------------------------------------------

def _leg1_curl(url: str) -> dict:
    """
    Fetch the page with curl_cffi and extract locale URLs, hreflang variants, CMP script signals, and redirect chain.
    Returns a result dict; on failure sets 'success': False and 'error'.
    """
    result = {
        "success": False,
        "hreflang_variants": [],
        "hreflang_x_default_href": None,
        "locale_urls": {},
        "http_link_header": None,
        "cookie_provider": None,
        "landed_url": url,
        "error": None,
    }
    if not _CURL_CFFI_AVAILABLE or not _BS4_AVAILABLE:
        result["error"] = "curl_cffi or bs4 not available"
        return result

    try:
        # create curl request and store url after redirects from base
        r = _creq.get(url, impersonate="chrome", headers=_CURL_HEADERS,
                      timeout=15, allow_redirects=True)
        result["landed_url"] = r.url
        body = r.text
        result["http_link_header"] = r.headers.get("link")

        # error if we don't have 200
        if r.status_code != 200:
            result["error"] = f"HTTP {r.status_code}"
            return result

        soup = _BS(body, "lxml") if _BS4_AVAILABLE else None

        hreflang_variants = []
        locale_urls = {}

        # look for hreflang tags or href in general
        for tag in soup.find_all("link", rel="alternate"):
            lang = tag.get("hreflang", "")
            href = tag.get("href", "")
            if not lang or not href:
                continue
            if lang.lower() == "x-default":
                result["hreflang_x_default_href"] = href
            else:
                code = _normalize_lang(lang)
                if _is_probable_lang_code(code):
                    _add_locale_candidate(locale_urls, code, href)
                v = lang.replace("_", "-").upper()
                if v in KNOWN_LANGUAGE_VARIANTS:
                    hreflang_variants.append(v)
        result["hreflang_variants"] = hreflang_variants
        result["locale_urls"] = locale_urls

        # CMP script signals, same pattern list as Playwright Strategy 1
        _CMP_SCRIPT_SIGNALS = [
            ("OneTrust",       ["cdn.cookielaw.org", "optanon.blob.core.windows.net"]),
            ("Cookiebot",      ["consent.cookiebot.com", "cookiebot.com/uc.js"]),
            ("Didomi",         ["sdk.privacy-center.org", "didomi.io"]),
            ("TrustArc",       ["consent.trustarc.com", "trustarc.com/notice"]),
            ("CookieYes",      ["cdn-cookieyes.com", "app.cookieyes.com"]),
            ("Osano",          ["cmp.osano.com"]),
            ("Axeptio",        ["static.axept.io"]),
            ("Iubenda",        ["cdn.iubenda.com/cs/iubenda_cs.js"]),
            ("Usercentrics",   ["app.usercentrics.eu", "privacy-proxy.usercentrics.eu"]),
            ("Sourcepoint",    ["sourcepoint.com", "sp-prod.net", "cdn.privacy-mgmt.com"]),
            ("Quantcast",      ["cmp.quantcast.com"]),
            ("Termly",         ["app.termly.io"]),
            ("CookieScript",   ["cookiescriptcdn.pro", "cookie-script.com"]),
            ("Complianz",      ["cdn.complianz.io"]),
            ("CookieFirst",    ["consent.cookiefirst.com"]),
            ("Consentmanager", ["cdn.consentmanager.net"]),
            ("Civic",          ["cc.cdn.civiccomputing.com"]),
            ("PiwikPRO",       ["piwik.pro"]),
            ("Cookieconsent",  ["cookieconsent.min.js", "cookieconsent.js", "/cookieconsent/"]),
            ("Tarteaucitron",  ["tarteaucitron.js", "tarteaucitron.min.js", "tarteaucitron.io"]),
            ("Klaro",          ["klaro.js", "kiprotect.com/klaro"]),
            ("Borlabs",        ["borlabs-cookie/js/", "borlabs-cookie.min.js"]),
            ("SFBX",           ["sfbx.com", "consenso.sfbx.com"]),
            ("CCM19",          ["cdn.ccm19.de", "ccm19.de"]),
            ("Cookiehub",      ["cookiehub.com"]),
            ("TrustCommander", ["tagcommander.com", "commander1.com"]),
            ("Webcare",        ["webcare.io"]),
        ]
        script_srcs = [s.get("src", "") for s in soup.find_all("script", src=True)]
        for provider, patterns in _CMP_SCRIPT_SIGNALS:
            if any(p in src for src in script_srcs for p in patterns):
                result["cookie_provider"] = provider
                break

        result["success"] = True

    except Exception as e:
        result["error"] = str(e)[:200]

    return result


# ---------------------------------------------------------------------------
# Leg 2: Sitemap hreflang check
# ---------------------------------------------------------------------------

def _leg2_sitemap(base_url: str) -> dict:
    """
    Fetch robots.txt, crawl sitemaps, and scan xhtml:link hreflang entries.
    Returns langs found, locale_urls, and per-sitemap status.
    """
    result = {
        "langs": [],
        "locale_urls": {},
        "sitemap_statuses": {},
    }
    if not _CURL_CFFI_AVAILABLE:
        return result

    parsed = urlparse(base_url)
    root_base = f"{parsed.scheme}://{parsed.netloc}"

    # Get sitemap URLs from robots.txt
    sitemap_urls = []
    try:
        r = _creq.get(f"{root_base}/robots.txt", impersonate="chrome",
                      headers=_CURL_HEADERS, timeout=10, allow_redirects=True)
        text = r.text
        if "<html" not in text[:300].lower():
            sitemap_urls = [
                ln.split(":", 1)[1].strip()
                for ln in text.splitlines()
                if ln.strip().lower().startswith("sitemap:")
            ]
    except Exception:
        pass
    # if no sitemaps found in robots.txt, default to /sitemap.xml
    if not sitemap_urls:
        sitemap_urls = [f"{root_base}/sitemap.xml"]

    langs_seen = set()
    locale_urls = {}
    seen_sitemaps = set()

    def _parse_sitemap(sm_url: str, depth: int = 0):
        """Recursively parse a sitemap URL, looking for hreflang links in url entries, 
        and recursing into nested sitemaps if it's a sitemap index. Depth is tracked to avoid infinite recursion."""
        if depth > 3 or sm_url in seen_sitemaps:
            return
        seen_sitemaps.add(sm_url)

        try:
            # fetch the sitemap, decompress if needed, and parse as XML
            r = _creq.get(sm_url, impersonate="chrome", headers=_CURL_HEADERS,
                          timeout=15, allow_redirects=True)
            body = r.content

            # decompres if needed (file extension or magic bytes)
            if sm_url.endswith(".gz") or body[:2] == b"\x1f\x8b":
                body = gzip.decompress(body)
            body_text = body[:300].decode("utf-8", "replace")

            if r.status_code != 200:
                result["sitemap_statuses"][sm_url] = f"http_error_{r.status_code}"
                return
            # means we hit a block
            if "<html" in body_text.lower():
                result["sitemap_statuses"][sm_url] = "blocked"
                return

            # parse bytes as xml
            root = ET.fromstring(body)
        except ET.ParseError:
            result["sitemap_statuses"][sm_url] = "failed"
            return
        except Exception:
            result["sitemap_statuses"][sm_url] = "failed"
            return

        # get tag name, namespace, and prefix (namespace is needed to find elements with namespaces)
        tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
        ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
        pfx = f"{{{ns}}}" if ns else ""

        # recursively parse if its a sitemap index. Limit to 10 nested  sitemaps. 
        if tag == "sitemapindex":
            result["sitemap_statuses"][sm_url] = "ok"
            for sm in root.findall(f"{pfx}sitemap")[:10]:
                loc = sm.find(f"{pfx}loc")
                if loc is not None and loc.text:
                    _parse_sitemap(loc.text.strip(), depth + 1)
        # if it's a urlset, look for hreflang links in url entries
        else:
            result["sitemap_statuses"][sm_url] = "ok"
            for url_el in root.findall(f"{pfx}url"):
                for link in url_el.findall(f"{{{_SITEMAP_XHTML_NS}}}link"):

                    # look for hreflang links and extract lang codes. 
                    if link.get("rel") == "alternate" and link.get("hreflang"):
                        lang = link.get("hreflang", "")
                        href = link.get("href", "")
                        if lang.lower() != "x-default" and href:
                            langs_seen.add(lang.lower())
                            code = _normalize_lang(lang)
                            if _is_probable_lang_code(code):
                                _add_locale_candidate(locale_urls, code, href)
    # start initial sitemap parsing
    for sm_url in sitemap_urls:
        _parse_sitemap(sm_url)

    result["langs"] = sorted(langs_seen)
    result["locale_urls"] = locale_urls
    return result


# ---------------------------------------------------------------------------
#  Playwright crawler function that is publically accessible
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
        "translation_plugin": None,
        "hreflang_source": None,
        "landed_url": None,
    }

    # Legs 1+2 run in parallel threads while Playwright starts up.
    plog(f"[leg1] Starting curl fetch for {url} (parallel with Playwright)")
    plog(f"[leg2] Starting sitemap check for {url} (parallel with Playwright)")
    _leg_pool = ThreadPoolExecutor(max_workers=2)
    _fut_leg1 = _leg_pool.submit(_leg1_curl, url)
    _fut_leg2 = _leg_pool.submit(_leg2_sitemap, url)

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                )
            )
            # Hide the Playwright webdriver flag (reduces bot detection apparently)
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page.set_default_timeout(15000)

            plog(f"[crawler] Loading {url} ...")
            try:
                _nav_resp = page.goto(url, wait_until="domcontentloaded")
            except Exception as nav_err:
                # retry http version if we get protocol error
                if "ERR_HTTP2_PROTOCOL_ERROR" in str(nav_err):
                    plog(f"[crawler] HTTP/2 error, retrying with HTTP/1.1...")
                    browser.close()
                    browser = p.chromium.launch(headless=True, args=["--disable-http2", "--no-sandbox", "--disable-setuid-sandbox"])
                    page = browser.new_page(
                        user_agent=(
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/131.0.0.0 Safari/537.36"
                        )
                    )
                    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                    page.set_default_timeout(15000)
                    _nav_resp = page.goto(url, wait_until="domcontentloaded")
                else:
                    raise
            plog(f"[crawler] HTTP {_nav_resp.status if _nav_resp else 0} | title={page.title()!r} | body={len(page.content())} chars")

            # Wait for hreflang tags to appear since they can be injected after document loaded
            try:
                page.wait_for_selector('link[rel="alternate"][hreflang]', state="attached", timeout=5000)
            except Exception:
                # Site has no hreflang tags, or they didn't load in time.
                # Give JS-rendered locales a bit more time before locale detection.
                page.wait_for_timeout(3000)

            # extract hreflang tags
            raw_hreflang = page.evaluate("""() => {
                return Array.from(
                    document.querySelectorAll('link[rel="alternate"][hreflang]')
                ).map(el => ({ lang: el.hreflang.toLowerCase(), href: el.href }));
            }""")

            # fill in hreflang and xdefault results
            result["hreflang_present"] = len(raw_hreflang) > 0
            x_default = next((t for t in raw_hreflang if t.get("lang") == "x-default"), None)
            result["hreflang_x_default_present"] = x_default is not None
            result["hreflang_x_default_url"] = x_default.get("href") if x_default else None

            # store full variants 
            variant_set = {
                str(t.get("lang", "")).replace("_", "-").upper()
                for t in raw_hreflang
                if t.get("lang") and str(t.get("lang")).lower() != "x-default"
            }

            locale_urls = _detect_locale_urls(page, url)

            # get lang for homepage and add to locale candidates if valid and not already present
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
            result["available_language_variants"] = sorted(
                code for code in variant_set if code in KNOWN_LANGUAGE_VARIANTS
            )
            result["language_selector_type"] = _detect_language_selector_type(page)

            # Give GTM-injected CMPs time to fire before checking the DOM.
            page.wait_for_timeout(10000)
            
            # check for cookies
            cookie_info = _detect_cookie_banner(page)
            result["cookie_banner_detected"] = cookie_info.get("detected", False)
            result["cookie_provider"] = cookie_info.get("provider")
            plog(f"[crawler] Cookie banner: {result['cookie_banner_detected']} (provider: {result['cookie_provider']})")

            # check to see if the site uses a plugin
            plugin_info = _detect_translation_plugin(page)
            result["translation_plugin"] = plugin_info.get("plugin")
            if result["translation_plugin"] and plugin_info.get("languages"):
                for lang_code in plugin_info["languages"]:
                    upper = lang_code.replace("_", "-").upper()
                    key = upper if upper in KNOWN_LANGUAGE_VARIANTS else _normalize_lang(lang_code)
                    if (key in KNOWN_LANGUAGE_VARIANTS or _is_probable_lang_code(key)) and key not in result["locale_urls"]:
                        result["locale_urls"][key] = url
                result["available_languages"] = sorted(result["locale_urls"].keys())
            plog(f"[crawler] Translation plugin: {result['translation_plugin']} (languages: {plugin_info.get('languages', [])})")

            plog(f"[crawler] Found {len(locale_urls)} locales: {list(locale_urls.keys())}")

            browser.close()
            plog(f"[crawler] Pillar 1 crawl complete. "
                  f"{result['pages_checked']} pages checked, "
                  f"{len(result['mixed_language_issues'])} locales with mixed-language markers.")

    except Exception as e:
        result["crawler_error"] = str(e)
        plog(f"[crawler] ERROR: {e}")

    # Collect leg results (finished during Playwright execution)
    leg1 = _fut_leg1.result()
    leg2 = _fut_leg2.result()
    _leg_pool.shutdown(wait=False)

    if leg1["success"]:
        plog(f"[leg1] OK — {len(leg1['locale_urls'])} hreflang locale URLs, "
             f"variants={leg1['hreflang_variants']}, "
             f"CMP: {leg1['cookie_provider']}, landed: {leg1['landed_url']}")
        if leg1["http_link_header"]:
            plog(f"[leg1] HTTP Link header: {leg1['http_link_header']}")
    else:
        plog(f"[leg1] FAILED — {leg1['error']}")
    plog(f"[leg2] langs={leg2['langs']}, locale_urls={len(leg2['locale_urls'])}, "
         f"statuses={leg2['sitemap_statuses']}")

    # --- Merge ---
    # Save Playwright's findings before overwriting
    pw_has_hreflang = result["hreflang_present"]
    pw_locale_urls = result["locale_urls"]

    # locale_urls: priority order — leg1 hreflang > leg2 sitemap > Playwright
    merged_locale_urls = {}
    if leg1["success"]:
        for code, href in leg1["locale_urls"].items():
            _add_locale_candidate(merged_locale_urls, code, href)
    for code, href in leg2["locale_urls"].items():
        _add_locale_candidate(merged_locale_urls, code, href)
    for code, href in pw_locale_urls.items():
        _add_locale_candidate(merged_locale_urls, code, href)
    result["locale_urls"] = merged_locale_urls
    result["available_languages"] = sorted(merged_locale_urls.keys())

    # available_language_variants: union from all three sources
    all_variants = set(result.get("available_language_variants", []))
    if leg1["success"]:
        all_variants.update(leg1["hreflang_variants"])
    for lang in leg2["langs"]:
        v = lang.replace("_", "-").upper()
        if v in KNOWN_LANGUAGE_VARIANTS:
            all_variants.add(v)
    result["available_language_variants"] = sorted(all_variants)

    # hreflang fields
    leg1_has_hreflang = leg1["success"] and len(leg1["locale_urls"]) > 0
    leg2_has_hreflang = len(leg2["langs"]) > 0
    result["hreflang_present"] = leg1_has_hreflang or leg2_has_hreflang or pw_has_hreflang

    if leg1_has_hreflang:
        result["hreflang_x_default_present"] = leg1["hreflang_x_default_href"] is not None
        result["hreflang_x_default_url"] = leg1["hreflang_x_default_href"]

    # hreflang_source
    if leg1_has_hreflang:
        result["hreflang_source"] = "html_head"
    elif leg2_has_hreflang:
        result["hreflang_source"] = "sitemap"
    elif pw_has_hreflang:
        result["hreflang_source"] = "js_injected"
    else:
        result["hreflang_source"] = "none"

    # cookie_provider: leg1 script signal wins if found, else keep Playwright's
    if leg1.get("cookie_provider"):
        result["cookie_provider"] = leg1["cookie_provider"]
        result["cookie_banner_detected"] = True

    # landed_url from leg1 redirect chain
    if leg1["success"]:
        result["landed_url"] = leg1["landed_url"]

    result["crawler_ran"] = True

    plog(f"[merge] hreflang_source={result['hreflang_source']} | "
         f"hreflang_present={result['hreflang_present']} | "
         f"available_languages={result['available_languages']} | "
         f"locale_urls={len(result['locale_urls'])}")

    return result

def _flatten_mixed_language_issues(issues: list) -> list:
    """
    Rescue locale issue objects that GPT nested inside language_hits instead of placing at the top level. 
    Any language_hits item that contains a 'locale' key is a misplaced locale issue, not a real language hit.
    """
    result = []
    for issue in issues:
        real_hits = []
        rescued = []
        for hit in issue.get('language_hits', []):
            if 'locale' in hit:
                #  hit has both language/marker_strings AND locale properties
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

# ---------------------------------------------------------------------------
# GPT-5 mixed language detection
# ---------------------------------------------------------------------------

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

        # try json repair as resort if malformed json is returned
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
