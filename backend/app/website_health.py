"""
Pillar 2: Website Health data gathering for Powerling Pre-Audit.

Data sources (all free, no auth required for basic use):
  1. Google PageSpeed Insights API
     - Client homepage: mobile + desktop
     - Client locale pages: mobile only (URLs from Pillar 1 crawler)
     - Competitor homepages: mobile + desktop (benchmark only)
  2. Homepage technical checks (requests + HTML parsing)
     - robots.txt, sitemap.xml, llms.txt presence
     - HSTS header, HTTP -> HTTPS redirect
     - Schema.org markup types
     - H1 count

SEMrush integration is intentionally left as a pass-through:
  gather_pillar2_facts() accepts semrush_data=None; pass parsed
  parse_semrush_pdf() output here when that integration is ready.
"""

import json
import os
import re
import time
from typing import Dict, List, Optional
from urllib.parse import urlparse, urljoin

import requests

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
_HTTP_TIMEOUT = 12   # seconds for simple GET checks
_PSI_CONNECT_TIMEOUT = 10
_PSI_READ_TIMEOUT = 70
_PSI_DELAY = 0.5     # seconds between PSI calls (courtesy, not required)

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PowerlingAudit/1.0)"}


# ---------------------------------------------------------------------------
# PageSpeed Insights - internal helpers
# ---------------------------------------------------------------------------

def _score(data: dict, category: str) -> Optional[int]:
    """Extract 0-100 category score from a PSI response dict."""
    try:
        raw = data["lighthouseResult"]["categories"][category]["score"]
        return round(raw * 100) if raw is not None else None
    except (KeyError, TypeError):
        return None


def _audit_score(data: dict, key: str) -> Optional[float]:
    """Extract a raw 0.0-1.0 audit score."""
    try:
        return data["lighthouseResult"]["audits"][key]["score"]
    except (KeyError, TypeError):
        return None


def _audit_display(data: dict, key: str) -> Optional[str]:
    """Extract the human-readable displayValue for an audit."""
    try:
        return data["lighthouseResult"]["audits"][key].get("displayValue")
    except (KeyError, TypeError):
        return None


def _cwv(data: dict, metric: str) -> Optional[str]:
    """
    Extract Core Web Vitals field-data category from PSI loadingExperience.
    Returns 'GOOD', 'NEEDS_IMPROVEMENT', 'POOR', or None.
    """
    try:
        return data["loadingExperience"]["metrics"][metric]["category"]
    except (KeyError, TypeError):
        return None


def _parse_psi_response(data: dict, url: str, strategy: str) -> dict:
    """Flatten a raw PSI JSON response into a structured dict."""
    s = lambda key: _audit_score(data, key)
    d = lambda key: _audit_display(data, key)

    return {
        "url": url,
        "strategy": strategy,
        "psi_ran": True,
        "psi_error": None,
        # Category scores (0-100)
        "performance_score": _score(data, "performance"),
        "accessibility_score": _score(data, "accessibility"),
        "best_practices_score": _score(data, "best-practices"),
        "seo_score": _score(data, "seo"),
        # Core Web Vitals - lab data (Lighthouse simulation)
        "lcp": d("largest-contentful-paint"),
        "lcp_score": s("largest-contentful-paint"),
        "cls": d("cumulative-layout-shift"),
        "cls_score": s("cumulative-layout-shift"),
        "inp": d("interaction-to-next-paint"),
        "inp_score": s("interaction-to-next-paint"),
        "fcp": d("first-contentful-paint"),
        "tbt": d("total-blocking-time"),
        "speed_index": d("speed-index"),
        "server_response_time": d("server-response-time"),
        # CWV - field data (real user measurements, when available)
        "cwv_lcp_category": _cwv(data, "LARGEST_CONTENTFUL_PAINT_MS"),
        "cwv_cls_category": _cwv(data, "CUMULATIVE_LAYOUT_SHIFT_SCORE"),
        "cwv_inp_category": _cwv(data, "INTERACTION_TO_NEXT_PAINT"),
        "cwv_fcp_category": _cwv(data, "FIRST_CONTENTFUL_PAINT_MS"),
        # Core performance metrics (display values + scores)
        "time_to_interactive": d("interactive"),
        "time_to_interactive_score": s("interactive"),
        "total_blocking_time_score": s("total-blocking-time"),
        "speed_index_score": s("speed-index"),
        # SEO sub-audits: 1.0 = pass, 0.0 = fail, None = informational
        "has_meta_description": s("meta-description") == 1,
        "has_document_title": s("document-title") == 1,
        "hreflang_audit_pass": s("hreflang") == 1,
        "has_canonical": s("canonical") == 1,
        "robots_txt_valid": s("robots-txt") == 1,
        "is_crawlable": s("is-crawlable") == 1,
        "image_alt_score": s("image-alt"),
        "crawlable_anchors_score": s("crawlable-anchors"),
        "tap_targets_score": s("tap-targets"),
        "font_size_ok": s("font-size") == 1,
        "link_text_ok": s("link-text") == 1,
        # Performance opportunities (True = issue present; *_savings = human-readable estimate)
        "render_blocking_resources": s("render-blocking-resources") is not None
                                     and s("render-blocking-resources") < 0.9,
        "render_blocking_savings": d("render-blocking-resources"),
        "unused_javascript": s("unused-javascript") is not None
                             and s("unused-javascript") < 0.9,
        "unused_javascript_savings": d("unused-javascript"),
        "unused_css": s("unused-css-rules") is not None
                      and s("unused-css-rules") < 0.9,
        "unused_css_savings": d("unused-css-rules"),
        "unminified_javascript": s("unminified-javascript") is not None
                                 and s("unminified-javascript") < 0.9,
        "unminified_javascript_savings": d("unminified-javascript"),
        "unminified_css": s("unminified-css") is not None
                          and s("unminified-css") < 0.9,
        "unminified_css_savings": d("unminified-css"),
        # Image optimisation (True = issue present / savings available)
        "unoptimized_images": s("uses-optimized-images") is not None
                              and s("uses-optimized-images") < 0.9,
        "unoptimized_images_savings": d("uses-optimized-images"),
        "next_gen_images": s("uses-webp-images") is not None
                           and s("uses-webp-images") < 0.9,
        "next_gen_images_savings": d("uses-webp-images"),
        "offscreen_images": s("offscreen-images") is not None
                            and s("offscreen-images") < 0.9,
        "offscreen_images_savings": d("offscreen-images"),
        # Caching / network
        "uses_text_compression": s("uses-text-compression") == 1,
        "efficient_cache": s("uses-long-cache-ttl") is not None
                           and s("uses-long-cache-ttl") > 0.5,
        "cache_savings": d("uses-long-cache-ttl"),
        # Page structure
        "dom_size": d("dom-size"),
        "third_party_blocking_time": d("third-party-summary"),
    }


def _empty_psi(url: str, strategy: str, error: str = None) -> dict:
    """Return a zeroed-out PSI result for when the call fails."""
    return {
        "url": url, "strategy": strategy,
        "psi_ran": False, "psi_error": error,
        "performance_score": None, "accessibility_score": None,
        "best_practices_score": None, "seo_score": None,
        "lcp": None, "lcp_score": None, "cls": None, "cls_score": None,
        "inp": None, "inp_score": None, "fcp": None, "tbt": None,
        "speed_index": None, "server_response_time": None,
        "time_to_interactive": None, "time_to_interactive_score": None,
        "total_blocking_time_score": None, "speed_index_score": None,
        "cwv_lcp_category": None, "cwv_cls_category": None,
        "cwv_inp_category": None, "cwv_fcp_category": None,
        "has_meta_description": None, "has_document_title": None,
        "hreflang_audit_pass": None, "has_canonical": None,
        "robots_txt_valid": None, "is_crawlable": None,
        "image_alt_score": None, "crawlable_anchors_score": None,
        "tap_targets_score": None, "font_size_ok": None, "link_text_ok": None,
        "render_blocking_resources": None, "render_blocking_savings": None,
        "unused_javascript": None, "unused_javascript_savings": None,
        "unused_css": None, "unused_css_savings": None,
        "unminified_javascript": None, "unminified_javascript_savings": None,
        "unminified_css": None, "unminified_css_savings": None,
        "unoptimized_images": None, "unoptimized_images_savings": None,
        "next_gen_images": None, "next_gen_images_savings": None,
        "offscreen_images": None, "offscreen_images_savings": None,
        "uses_text_compression": None, "efficient_cache": None, "cache_savings": None,
        "dom_size": None, "third_party_blocking_time": None,
    }


# ---------------------------------------------------------------------------
# PageSpeed Insights - public API
# ---------------------------------------------------------------------------

def gather_pagespeed_data(
    url: str,
    strategy: str = "mobile",
    api_key: Optional[str] = None,
) -> dict:
    """
    Run PageSpeed Insights on a single URL.
    Returns structured metrics dict; on failure psi_ran=False and psi_error is set.

    api_key: optional Google Cloud API key (free quota: 25K/day vs ~400/day without)
             Pass os.environ.get("GOOGLE_PAGESPEED_API_KEY") or None.
    Retries on 429 + timeout/transient request failures with exponential backoff.
    """
    if api_key is None:
        api_key = os.environ.get("GOOGLE_PAGESPEED_API_KEY")

    params: Dict = {
        "url": url,
        "strategy": strategy,
        "category": ["performance", "accessibility", "best-practices", "seo"],
    }
    if api_key:
        params["key"] = api_key

    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            resp = requests.get(
                PSI_ENDPOINT,
                params=params,
                timeout=(_PSI_CONNECT_TIMEOUT, _PSI_READ_TIMEOUT),
                headers=_HEADERS,
            )
            if resp.status_code == 429 and attempt < (max_attempts - 1):
                backoff = 15 * (attempt + 1)
                print(f"[p2]   PSI rate-limited ({strategy}, {url}), retrying in {backoff}s...")
                time.sleep(backoff)
                continue
            resp.raise_for_status()
            return _parse_psi_response(resp.json(), url, strategy)
        except requests.exceptions.Timeout as e:
            if attempt < (max_attempts - 1):
                backoff = 5 * (attempt + 1)
                print(f"[p2]   PSI timeout ({strategy}, {url}), retrying in {backoff}s...")
                time.sleep(backoff)
                continue
            print(f"[p2]   PSI timeout ({strategy}, {url}): {e}")
            return _empty_psi(url, strategy, f"timeout: {e}")
        except requests.exceptions.RequestException as e:
            if attempt < (max_attempts - 1):
                backoff = 3 * (attempt + 1)
                print(f"[p2]   PSI request failed ({strategy}, {url}), retrying in {backoff}s...")
                time.sleep(backoff)
                continue
            print(f"[p2]   PSI failed ({strategy}, {url}): {e}")
            return _empty_psi(url, strategy, str(e))
        except Exception as e:
            print(f"[p2]   PSI failed ({strategy}, {url}): {e}")
            return _empty_psi(url, strategy, str(e))

    return _empty_psi(url, strategy, "rate-limited after retry")


# ---------------------------------------------------------------------------
# Homepage technical checks (requests + HTML parsing, no Playwright needed)
# ---------------------------------------------------------------------------

def _check_path(base: str, path: str) -> bool:
    """GET base + path, return True if response is 200."""
    try:
        target = urljoin(base.rstrip("/") + "/", path.lstrip("/"))
        r = requests.get(target, timeout=_HTTP_TIMEOUT, allow_redirects=True,
                         headers=_HEADERS)
        return r.status_code == 200
    except Exception:
        return False


def _check_https_redirect(url: str) -> bool:
    """Return True if the http:// version 301/302-redirects to https://."""
    parsed = urlparse(url)
    http_url = f"http://{parsed.netloc}{parsed.path or '/'}"
    try:
        r = requests.get(http_url, timeout=_HTTP_TIMEOUT, allow_redirects=False,
                         headers=_HEADERS)
        location = r.headers.get("Location", "")
        return r.status_code in (301, 302, 307, 308) and location.startswith("https://")
    except Exception:
        return False


def _extract_schema_types(html: str) -> List[str]:
    """Return sorted list of Schema.org @type values found in LD+JSON blocks."""
    types: set = set()
    blocks = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE,
    )
    for block in blocks:
        try:
            data = json.loads(block)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict):
                    t = item.get("@type")
                    if isinstance(t, str):
                        types.add(t)
                    elif isinstance(t, list):
                        types.update(t)
        except Exception:
            pass
    return sorted(types)


def _extract_h1_texts(html: str) -> List[str]:
    """Return list of H1 text values (stripped of inner tags, capped at 3)."""
    matches = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL | re.IGNORECASE)
    results = []
    for m in matches:
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m)).strip()
        if text:
            results.append(text[:120])
    return results[:3]


def gather_homepage_technical_facts(url: str) -> dict:
    """
    Fetch the homepage once and extract technical signals that PSI doesn't expose:
      - robots.txt / sitemap.xml / llms.txt presence
      - HSTS header
      - HTTP -> HTTPS redirect
      - Schema.org @type markup
      - H1 count and text
    Uses only the requests library; no Playwright dependency.
    """
    result = {
        "has_robots_txt": False,
        "has_sitemap_xml": False,
        "has_llms_txt": False,
        "hsts_present": False,
        "https_redirect": False,
        "h1_count": None,
        "h1_texts": [],
        "schema_types": [],
        "checker_ran": False,
        "checker_error": None,
    }
    try:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"

        # Fetch homepage to get response headers + HTML
        r = requests.get(url, timeout=_HTTP_TIMEOUT, allow_redirects=True,
                         headers=_HEADERS)
        html = r.text

        result["hsts_present"] = "strict-transport-security" in {
            k.lower() for k in r.headers
        }

        h1s = _extract_h1_texts(html)
        result["h1_count"] = len(h1s)
        result["h1_texts"] = h1s
        result["schema_types"] = _extract_schema_types(html)

        result["has_robots_txt"] = _check_path(base, "/robots.txt")
        result["has_sitemap_xml"] = _check_path(base, "/sitemap.xml")
        result["has_llms_txt"] = _check_path(base, "/llms.txt")
        result["https_redirect"] = _check_https_redirect(url)

        result["checker_ran"] = True
    except Exception as e:
        result["checker_error"] = str(e)
        print(f"[p2]   Homepage technical check failed: {e}")

    return result


# ---------------------------------------------------------------------------
# Orchestration - client site
# ---------------------------------------------------------------------------

def gather_pillar2_facts(
    url: str,
    locale_urls: Optional[Dict[str, str]] = None,
    semrush_data: Optional[dict] = None,
    api_key: Optional[str] = None,
) -> dict:
    """
    Full Pillar 2 data gathering for the client site.

    url:          client homepage URL
    locale_urls:  {lang_code: url} dict from the Pillar 1 crawler
    semrush_data: parsed SEMrush PDF output (pass None to skip - integrate later)
    api_key:      optional GOOGLE_PAGESPEED_API_KEY for higher rate limits
    """
    print(f"[p2] Gathering website health for {url} ...")
    if api_key is None:
        api_key = os.environ.get("GOOGLE_PAGESPEED_API_KEY")
    if not api_key:
        print("[p2]   No GOOGLE_PAGESPEED_API_KEY provided; using lower unauthenticated quota.")

    # SEMrush fields - populated when semrush_data is provided; all None otherwise
    def _sem(key):
        return semrush_data.get(key) if semrush_data else None

    result = {
        "psi_ran": False,
        "semrush_available": semrush_data is not None,
        "pages_tested": 0,
        # Homepage PSI (nested dicts)
        "homepage_mobile": {},
        "homepage_desktop": {},
        # Locale page PSI results
        "locale_psi_results": [],
        "locale_performance_min": None,
        "locale_performance_max": None,
        "locale_performance_avg": None,
        "locale_desktop_performance_min": None,
        "locale_desktop_performance_max": None,
        "locale_desktop_performance_avg": None,
        # Top-level SEO/performance flags (promoted from homepage mobile)
        "performance_score_mobile": None,
        "performance_score_desktop": None,
        "seo_score_mobile": None,
        "accessibility_score_mobile": None,
        "lcp_mobile": None,
        "cls_mobile": None,
        "inp_mobile": None,
        "lcp_desktop": None,
        "cwv_lcp_category": None,
        "cwv_cls_category": None,
        "cwv_inp_category": None,
        "has_meta_description": None,
        "has_canonical": None,
        "hreflang_audit_pass": None,
        "robots_txt_valid": None,
        "image_alt_score": None,
        "is_crawlable": None,
        "render_blocking_resources": None,
        "unused_javascript": None,
        "unused_css": None,
        "uses_text_compression": None,
        # Homepage technical checks
        "has_robots_txt": None,
        "has_sitemap_xml": None,
        "has_llms_txt": None,
        "hsts_present": None,
        "https_redirect": None,
        "h1_count": None,
        "h1_texts": [],
        "schema_types": [],
        # SEMrush fields (None unless semrush_data provided)
        "site_health_score": _sem("site_health_score"),
        "errors_total": _sem("errors_total"),
        "warnings_total": _sem("warnings_total"),
        "notices_total": _sem("notices_total"),
        "broken_internal_links": _sem("broken_internal_links"),
        "broken_external_links": _sem("broken_external_links"),
        "duplicate_content_pages": _sem("duplicate_content_pages"),
        "missing_meta_descriptions": _sem("missing_meta_descriptions"),
        "hreflang_conflicts": _sem("hreflang_conflicts"),
        "hreflang_language_mismatch": _sem("hreflang_language_mismatch"),
        "pages_deep_crawl": _sem("pages_deep_crawl"),
        "unminified_js_css": _sem("unminified_js_css"),
        "temporary_redirects": _sem("temporary_redirects"),
        "permanent_redirects": _sem("permanent_redirects"),
        "pages_crawled": _sem("pages_crawled"),
        "images_missing_alt": _sem("images_missing_alt"),
        "multiple_h1_pages": _sem("multiple_h1_pages"),
        "pages_slow_load": _sem("pages_slow_load"),
    }

    # 1. Homepage PSI - mobile
    print(f"[p2]   PSI homepage mobile ...")
    mobile = gather_pagespeed_data(url, strategy="mobile", api_key=api_key)
    result["homepage_mobile"] = mobile
    if mobile.get("psi_ran"):
        result["psi_ran"] = True
        result["pages_tested"] += 1
        result["performance_score_mobile"] = mobile.get("performance_score")
        result["seo_score_mobile"] = mobile.get("seo_score")
        result["accessibility_score_mobile"] = mobile.get("accessibility_score")
        result["lcp_mobile"] = mobile.get("lcp")
        result["cls_mobile"] = mobile.get("cls")
        result["inp_mobile"] = mobile.get("inp")
        result["cwv_lcp_category"] = mobile.get("cwv_lcp_category")
        result["cwv_cls_category"] = mobile.get("cwv_cls_category")
        result["cwv_inp_category"] = mobile.get("cwv_inp_category")
        for field in [
            "has_meta_description", "has_canonical", "hreflang_audit_pass",
            "robots_txt_valid", "image_alt_score", "is_crawlable",
            "render_blocking_resources", "render_blocking_savings",
            "unused_javascript", "unused_javascript_savings",
            "unused_css", "unused_css_savings",
            "unminified_javascript", "unminified_javascript_savings",
            "unminified_css", "unminified_css_savings",
            "unoptimized_images", "unoptimized_images_savings",
            "next_gen_images", "next_gen_images_savings",
            "offscreen_images", "offscreen_images_savings",
            "uses_text_compression", "efficient_cache", "cache_savings",
            "dom_size", "third_party_blocking_time",
            "time_to_interactive", "time_to_interactive_score",
            "total_blocking_time_score", "speed_index_score",
            "font_size_ok", "link_text_ok",
        ]:
            result[field] = mobile.get(field)

        # PSI fallbacks for SEMrush-equivalent fields (homepage mobile, single-page estimates)
        if semrush_data is None:
            unmin = mobile.get("unminified_javascript") or mobile.get("unminified_css")
            result["unminified_js_css"] = unmin if unmin is not None else None
            alt_score = mobile.get("image_alt_score")
            result["images_missing_alt"] = (alt_score < 1) if alt_score is not None else None
            result["pages_slow_load"] = (
                1 if (mobile.get("performance_score") is not None and mobile.get("performance_score") < 50) else 0
            )

    time.sleep(_PSI_DELAY)

    # 2. Homepage PSI - desktop
    print(f"[p2]   PSI homepage desktop ...")
    desktop = gather_pagespeed_data(url, strategy="desktop", api_key=api_key)
    result["homepage_desktop"] = desktop
    if desktop.get("psi_ran"):
        result["pages_tested"] += 1
        result["performance_score_desktop"] = desktop.get("performance_score")
        result["lcp_desktop"] = desktop.get("lcp")

    time.sleep(_PSI_DELAY)

    # 3. Locale page PSI - mobile + desktop, skip if same URL as homepage
    if locale_urls:
        homepage_norm = url.rstrip("/")
        for lang, locale_url in locale_urls.items():
            if locale_url.rstrip("/") == homepage_norm:
                continue
            print(f"[p2]   PSI locale {lang} mobile: {locale_url} ...")
            locale_mobile = gather_pagespeed_data(locale_url, strategy="mobile", api_key=api_key)
            if locale_mobile.get("psi_ran"):
                result["pages_tested"] += 1
            time.sleep(_PSI_DELAY)

            print(f"[p2]   PSI locale {lang} desktop: {locale_url} ...")
            locale_desktop = gather_pagespeed_data(locale_url, strategy="desktop", api_key=api_key)
            if locale_desktop.get("psi_ran"):
                result["pages_tested"] += 1
            time.sleep(_PSI_DELAY)

            result["locale_psi_results"].append({
                "lang": lang,
                "url": locale_url,
                # Mobile
                "performance_score": locale_mobile.get("performance_score"),
                "seo_score": locale_mobile.get("seo_score"),
                "lcp": locale_mobile.get("lcp"),
                "cls": locale_mobile.get("cls"),
                "has_meta_description": locale_mobile.get("has_meta_description"),
                "hreflang_audit_pass": locale_mobile.get("hreflang_audit_pass"),
                "psi_ran": locale_mobile.get("psi_ran"),
                "psi_error": locale_mobile.get("psi_error"),
                # Desktop
                "performance_score_desktop": locale_desktop.get("performance_score"),
                "lcp_desktop": locale_desktop.get("lcp"),
                "cls_desktop": locale_desktop.get("cls"),
                "psi_ran_desktop": locale_desktop.get("psi_ran"),
                "psi_error_desktop": locale_desktop.get("psi_error"),
            })

        mobile_scores = [
            r["performance_score"] for r in result["locale_psi_results"]
            if r.get("psi_ran") and r.get("performance_score") is not None
        ]
        if mobile_scores:
            result["locale_performance_min"] = min(mobile_scores)
            result["locale_performance_max"] = max(mobile_scores)
            result["locale_performance_avg"] = round(sum(mobile_scores) / len(mobile_scores), 1)

        desktop_scores = [
            r["performance_score_desktop"] for r in result["locale_psi_results"]
            if r.get("psi_ran_desktop") and r.get("performance_score_desktop") is not None
        ]
        if desktop_scores:
            result["locale_desktop_performance_min"] = min(desktop_scores)
            result["locale_desktop_performance_max"] = max(desktop_scores)
            result["locale_desktop_performance_avg"] = round(sum(desktop_scores) / len(desktop_scores), 1)

    # 4. Homepage technical checks
    print(f"[p2]   Homepage technical checks ...")
    tech = gather_homepage_technical_facts(url)
    if tech.get("checker_ran"):
        for field in [
            "has_robots_txt", "has_sitemap_xml", "has_llms_txt",
            "hsts_present", "https_redirect", "h1_count",
            "h1_texts", "schema_types",
        ]:
            result[field] = tech[field]

    print(
        f"[p2] Website health gather complete. "
        f"Pages tested: {result['pages_tested']}, "
        f"SEMrush: {'yes' if semrush_data else 'no'}"
    )
    return result


# ---------------------------------------------------------------------------
# Orchestration - competitor benchmark (homepage PSI only)
# ---------------------------------------------------------------------------

def gather_competitor_p2_facts(url: str, api_key: Optional[str] = None) -> dict:
    """
    Run PSI on a competitor's homepage (mobile + desktop) for benchmark data.
    Returns a compact dict that gets merged into the competitor's facts entry.
    """
    if api_key is None:
        api_key = os.environ.get("GOOGLE_PAGESPEED_API_KEY")

    print(f"[p2]   Competitor PSI: {url} ...")
    mobile = gather_pagespeed_data(url, strategy="mobile", api_key=api_key)
    time.sleep(_PSI_DELAY)
    desktop = gather_pagespeed_data(url, strategy="desktop", api_key=api_key)

    return {
        "p2_mobile_performance": mobile.get("performance_score"),
        "p2_mobile_seo": mobile.get("seo_score"),
        "p2_mobile_accessibility": mobile.get("accessibility_score"),
        "p2_mobile_lcp": mobile.get("lcp"),
        "p2_mobile_cls": mobile.get("cls"),
        "p2_mobile_inp": mobile.get("inp"),
        "p2_desktop_performance": desktop.get("performance_score"),
        "p2_desktop_seo": desktop.get("seo_score"),
        "p2_desktop_lcp": desktop.get("lcp"),
        "p2_cwv_lcp_category": mobile.get("cwv_lcp_category"),
        "p2_cwv_cls_category": mobile.get("cwv_cls_category"),
        "p2_cwv_inp_category": mobile.get("cwv_inp_category"),
        "p2_psi_ran": mobile.get("psi_ran") or desktop.get("psi_ran"),
    }
