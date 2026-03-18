"""
Pillar 1 crawler for Powerling Pre-Audit.

Visits the client's website using a headless browser to gather facts that
GPT-based web search cannot reliably detect:
  - Which language locales are actually available (from hreflang tags + switcher)
  - Whether any locale page displays French-language strings in CTAs or navigation
  - Whether hreflang tags are present at all

Results are merged into the facts pack, overriding the GPT-gathered pillar1_data
fields where the crawler produces more reliable values.
"""

import re  # used in _detect_locale_urls for URL path + lang text patterns
from urllib.parse import urlparse
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# French marker phrases
# These are unambiguous French words/phrases that should not appear on
# non-French locale pages. Lowercased for case-insensitive matching.
# ---------------------------------------------------------------------------

FRENCH_MARKERS = [
    "en savoir plus",
    "lire la suite",
    "en savoir",
    "savoir plus",
    "découvrir",
    "télécharger",
    "contactez-nous",
    "contactez nous",
    "nous contacter",
    "à propos",
    "accueil",
    "actualités",
    "nos solutions",
    "nos produits",
    "nos services",
    "notre équipe",
    "voir plus",
    "voir tout",
    "voir tous",
    "en voir plus",
]


# Default marker map for language-mix detection.
# Can be overridden via gather_pillar1_facts(..., marker_phrases_by_language=...)
DEFAULT_MARKER_PHRASES_BY_LANGUAGE = {
    "FR": FRENCH_MARKERS,
}


# Common languages used for URL/code validation.
COMMON_LANG_CODES = {
    "AR", "BG", "CS", "DA", "DE", "EL", "EN", "ES", "ET", "FA", "FI", "FR",
    "HE", "HI", "HR", "HU", "ID", "IT", "JA", "KO", "LT", "LV", "MS", "NL",
    "NO", "PL", "PT", "RO", "RU", "SK", "SL", "SR", "SV", "TH", "TR", "UK",
    "VI", "ZH",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_lang(raw: str) -> str:
    """
    Normalize a BCP-47 language tag to a simple 2-letter uppercase code.
    e.g. "en-US" -> "EN", "fr-BE" -> "FR", "fr_FR" -> "FR", "x-default" -> "X-DEFAULT"
    Handles both hyphen (hreflang) and underscore (og:locale) separators.
    """
    return re.split(r'[-_]', raw)[0].upper()


def _is_probable_lang_code(code: str) -> bool:
    """
    Conservative language code validation for inferred URL/text candidates.
    """
    return bool(code and re.fullmatch(r"[A-Z]{2}", code) and code in COMMON_LANG_CODES)


def _add_locale_candidate(locale_urls: dict, code: Optional[str], href: Optional[str]) -> None:
    """
    Add a locale URL candidate if valid and not already present.
    """
    if not code or not href:
        return
    clean = code.upper()
    if clean == "X-DEFAULT":
        return
    if clean not in locale_urls:
        locale_urls[clean] = href


def _extract_code_from_href(href: str, base_url: str) -> Optional[str]:
    """
    Infer language code from URL patterns:
      - path-based: /en/ or /fr-be/
      - query-based: ?lang=en, ?locale=fr
      - hash-based: #/de or #lang=es
      - subdomain-based: en.example.com, fr-be.example.com
    """
    if not href:
        return None

    # Query parameter strategy
    query_match = re.search(
        r"[?&](?:lang|locale|hl|language)=([a-z]{2}(?:[-_][a-z]{2})?)(?:[&#]|$)",
        href,
        re.IGNORECASE,
    )
    if query_match:
        code = _normalize_lang(query_match.group(1))
        if _is_probable_lang_code(code):
            return code

    # Hash strategy
    hash_match = re.search(
        r"#(?:/|.*(?:lang|locale)=)([a-z]{2}(?:[-_][a-z]{2})?)(?:[&#/]|$)",
        href,
        re.IGNORECASE,
    )
    if hash_match:
        code = _normalize_lang(hash_match.group(1))
        if _is_probable_lang_code(code):
            return code

    # Path strategy
    path_match = re.search(r"/(?:[a-z]{2}(?:[-_][a-z]{2})?)(?:/|$|\?)", href, re.IGNORECASE)
    if path_match:
        code = _normalize_lang(path_match.group(0).strip("/?"))
        if _is_probable_lang_code(code):
            return code

    # Subdomain strategy
    try:
        parsed_href = urlparse(href)
        parsed_base = urlparse(base_url)
        host = (parsed_href.hostname or "").lower()
        base_host = (parsed_base.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if base_host.startswith("www."):
            base_host = base_host[4:]

        host_parts = host.split(".")
        base_parts = base_host.split(".")
        if len(host_parts) >= 3 and len(base_parts) >= 2:
            host_root = ".".join(host_parts[-2:])
            base_root = ".".join(base_parts[-2:])
            if host_root == base_root:
                sub = host_parts[0]
                if re.fullmatch(r"[a-z]{2}(?:[-_][a-z]{2})?", sub, re.IGNORECASE):
                    code = _normalize_lang(sub)
                    if _is_probable_lang_code(code):
                        return code
    except Exception:
        return None

    return None


def _find_marker_strings(texts: List[str], markers: List[str]) -> List[str]:
    """
    Given a list of text strings and language markers,
    return strings containing any marker phrase.
    Deduplicates results.
    """
    found = set()
    for text in texts:
        lowered = text.strip().lower()
        if not lowered:
            continue
        for marker in markers:
            if marker in lowered:
                found.add(text.strip())
                break
    return sorted(found)


def _extract_interactive_texts(page) -> list:
    """
    Extract visible text from interactive elements: buttons, CTAs, nav links,
    card read-more links. These are where mixed-language issues most commonly
    appear (e.g. 'En savoir plus' on an English page).
    """
    return page.evaluate("""() => {
        const selectors = [
            'a', 'button',
            '[role="button"]',
            'nav a', '.nav a', '.menu a', '.navigation a',
            '.cta', '.btn', '[class*="cta"]', '[class*="btn"]',
            '.card a', '.news a', '.article a', '.post a',
        ];
        const seen = new Set();
        const results = [];
        for (const sel of selectors) {
            try {
                document.querySelectorAll(sel).forEach(el => {
                    const t = (el.innerText || el.textContent || '').trim();
                    if (t && t.length > 1 && t.length < 120 && !seen.has(t)) {
                        seen.add(t);
                        results.push(t);
                    }
                });
            } catch(e) {}
        }
        return results;
    }""")


def _detect_locale_urls(page, base_url: str) -> dict:
    """
    Discover locale URLs using multiple strategies:
    1. <link rel="alternate" hreflang="..."> tags in <head>
    2. Language switcher links in the DOM
    3. URL inference from query/hash/path/subdomain patterns

    Returns a dict mapping normalized lang code -> absolute URL.
    e.g. {"EN": "https://example.com/en/", "FR": "https://example.com/fr/"}
    """
    locale_urls = {}

    # Strategy 1: hreflang tags
    hreflang_tags = page.evaluate("""() => {
        return Array.from(
            document.querySelectorAll('link[rel="alternate"][hreflang]')
        ).map(el => ({ lang: el.hreflang, href: el.href }));
    }""")

    for tag in hreflang_tags:
        lang = tag.get("lang", "")
        href = tag.get("href", "")
        if lang and href and lang.lower() != "x-default":
            code = _normalize_lang(lang)
            _add_locale_candidate(locale_urls, code, href)

    # Strategy 2: language switcher DOM links
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

        # Infer lang code from hreflang attr, link text (e.g. "EN"), or URL path
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

    # Strategy 3: all anchors with URL-language hints (query/hash/path/subdomain)
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


def _detect_language_selector_type(page) -> str:
    """
    Heuristically determine what kind of language selector the site uses.
    """
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
# Main public function
# ---------------------------------------------------------------------------

def gather_pillar1_facts(
    url: str,
    target_languages: Optional[List[str]] = None,
    marker_phrases_by_language: Optional[Dict[str, List[str]]] = None,
    check_mixed_language: bool = True,
) -> dict:
    """
    Load the client's website with a headless browser and extract:
      - Available locale URLs (from hreflang or language switcher)
      - Whether hreflang tags are present
      - Mixed-language issues: marker strings found on each locale page
      - Language selector type

    check_mixed_language: if False, skip Step 4 (locale page visits for marker
      detection). Use False for competitor crawls where only available_languages
      and hreflang data are needed, to save time.

    Returns a dict that is merged into pillar_1_globalization in the facts pack.
    Fields returned here take precedence over GPT-gathered values.
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
    }

    marker_map = marker_phrases_by_language or DEFAULT_MARKER_PHRASES_BY_LANGUAGE
    normalized_marker_map = {
        _normalize_lang(lang): [m.lower() for m in (markers or []) if isinstance(m, str) and m.strip()]
        for lang, markers in marker_map.items()
        if isinstance(lang, str)
    }

    if target_languages:
        normalized_targets = [_normalize_lang(lang) for lang in target_languages if isinstance(lang, str) and lang.strip()]
    else:
        normalized_targets = sorted(normalized_marker_map.keys())

    # Keep only targets that have markers configured.
    normalized_targets = [lang for lang in normalized_targets if lang in normalized_marker_map]
    result["target_languages"] = normalized_targets

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(15000)

            # ----------------------------------------------------------------
            # Step 1: Load homepage
            # ----------------------------------------------------------------
            print(f"[crawler] Loading {url} ...")
            page.goto(url, wait_until="domcontentloaded")

            # ----------------------------------------------------------------
            # Step 2: Extract hreflang tags (raw, for the facts pack)
            # ----------------------------------------------------------------
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

            # Preserve full language variants when available (e.g. PT-PT, FR-BE),
            # while keeping available_languages as normalized 2-letter codes.
            variant_set = {
                str(t.get("lang", "")).replace("_", "-").upper()
                for t in raw_hreflang
                if t.get("lang") and str(t.get("lang")).lower() != "x-default"
            }

            # ----------------------------------------------------------------
            # Step 3: Discover locale URLs
            # ----------------------------------------------------------------
            locale_urls = _detect_locale_urls(page, url)

            # Add the homepage's own language if not already captured.
            # Sites often omit a self-referencing hreflang for their primary
            # language (e.g. lemonde.fr has no hreflang="fr" — French is implicit).
            # Try three sources in order of reliability:
            #   1. <html lang="...">
            #   2. <meta property="og:locale" content="fr_FR"> (widely used)
            html_lang = page.evaluate("""() => {
                return document.documentElement.lang
                    || document.querySelector('meta[property="og:locale"]')?.getAttribute('content')
                    || '';
            }""")
            print(f"[crawler] Homepage lang signal: {html_lang!r}")
            if html_lang:
                base_code = _normalize_lang(html_lang)
                if base_code and base_code not in ("X-DEFAULT",) and base_code not in locale_urls:
                    locale_urls[base_code] = url
                    print(f"[crawler] Added base language {base_code} from html/og:locale")

                html_variant = str(html_lang).replace("_", "-").upper()
                if html_variant and html_variant != "X-DEFAULT":
                    variant_set.add(html_variant)

            result["locale_urls"] = locale_urls
            result["available_languages"] = sorted(locale_urls.keys())
            result["available_language_variants"] = (
                sorted(variant_set) if variant_set else sorted(locale_urls.keys())
            )
            result["language_selector_type"] = _detect_language_selector_type(page)

            print(f"[crawler] Found {len(locale_urls)} locales: {list(locale_urls.keys())}")

            # ----------------------------------------------------------------
            # Step 4: Visit each locale page and check for mixed-language markers
            # Skipped when check_mixed_language=False (e.g. competitor crawls).
            # ----------------------------------------------------------------
            if check_mixed_language and normalized_targets:
                for lang_code, locale_url in locale_urls.items():
                    try:
                        print(f"[crawler] Checking locale {lang_code}: {locale_url}")
                        page.goto(locale_url, wait_until="domcontentloaded")
                        texts = _extract_interactive_texts(page)
                        result["pages_checked"] += 1

                        locale_base_lang = _normalize_lang(lang_code)
                        language_hits = []
                        for target_lang in normalized_targets:
                            if target_lang == locale_base_lang:
                                # Don't flag expected same-language markers on native locale pages.
                                continue
                            markers = normalized_marker_map.get(target_lang, [])
                            matched = _find_marker_strings(texts, markers)
                            if matched:
                                language_hits.append({
                                    "language": target_lang,
                                    "marker_strings_found": matched,
                                })

                        if language_hits:
                            issue = {
                                "locale": lang_code,
                                "page_url": locale_url,
                                "language_hits": language_hits,
                            }
                            # Backward-compatible field used by current test output.
                            fr_hit = next((h for h in language_hits if h["language"] == "FR"), None)
                            if fr_hit:
                                issue["french_strings_found"] = fr_hit["marker_strings_found"]

                            result["mixed_language_issues"].append(issue)
                            print(f"[crawler]   Mixed-language markers on {lang_code}: {language_hits}")
                        else:
                            print(f"[crawler]   No mixed-language markers on {lang_code}.")

                    except Exception as page_err:
                        print(f"[crawler]   Failed to check {lang_code}: {page_err}")
            else:
                print(f"[crawler] Skipping mixed-language check (check_mixed_language=False).")

            browser.close()
            result["crawler_ran"] = True
            print(f"[crawler] Pillar 1 crawl complete. "
                  f"{result['pages_checked']} pages checked, "
                f"{len(result['mixed_language_issues'])} locales with mixed-language markers.")

    except Exception as e:
        result["crawler_error"] = str(e)
        print(f"[crawler] ERROR: {e}")

    return result
