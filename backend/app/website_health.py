"""
Pillar 2: Website Health data gathering for Powerling Pre-Audit.

Data sources (all free, no auth required for basic use):
  1. Google PageSpeed Insights API
     - Client homepage: mobile + desktop
     - Client locale pages: mobile + desktop (URLs from Pillar 1 crawler)
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
from collections import Counter, deque
from typing import Dict, List, Optional
from urllib.parse import urlparse, urljoin

import requests

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
_HTTP_TIMEOUT = 12   # seconds for simple GET checks
_PSI_CONNECT_TIMEOUT = 10
_PSI_READ_TIMEOUT = 70
_PSI_DELAY = 0.5     # seconds between PSI calls (courtesy, not required)

_CRAWL_MAX_RETRIES = 3
_CRAWL_BACKOFF_429 = 5   # seconds; doubles each retry (5, 10, 20)
_CRAWL_BACKOFF_ERR = 2   # seconds for transient errors; doubles each retry

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
    max_crawl_pages: int = 100,
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
        # Site crawl fields (populated by gather_site_crawl_facts)
        "crawl_ran": False,
        "crawl_error": None,
        "broken_internal_urls": None,
        "https_to_http_links": None,
        "redirect_pages": None,
        "missing_title_pages": None,
        "short_title_pages": None,
        "long_title_pages": None,
        "duplicate_title_pages": None,
        "duplicate_meta_pages": None,
        "missing_h1_pages": None,
        "h1_duplicates_title_pages": None,
        "missing_canonical_pages": None,
        "pages_without_hreflang": None,
        "pages_hreflang_no_self": None,
        "thin_content_pages": None,
        "avg_word_count": None,
        "avg_text_to_html_ratio": None,
        "empty_anchor_links_total": None,
        "max_crawl_depth": None,
        "avg_crawl_depth": None,
        "pages_deep_crawl": None,
        "sitemap_urls_count": None,
        "orphan_pages": None,
        "crawl_scope_note": None,
        "broken_resources_pages": None,
        "dataforseo_task_id": None,
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

    # 3. Locale page PSI - disabled (not used in UI or generate_ui_content)
    # Re-enable when locale performance benchmarking is needed.

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

    # 5. Site crawl (DataForSEO OnPage API)
    print(f"[p2]   Site crawl via DataForSEO (up to {max_crawl_pages} pages) ...")
    try:
        from .dataforseo_crawl import gather_site_crawl_facts_dataforseo as _gather_crawl
    except ImportError:
        try:
            from dataforseo_crawl import gather_site_crawl_facts_dataforseo as _gather_crawl
        except ImportError:
            _gather_crawl = None

    if _gather_crawl:
        crawl = _gather_crawl(url, max_pages=max_crawl_pages)
    else:
        print("[p2]   dataforseo_crawl module not available, skipping crawl.")
        crawl = {"crawl_ran": False, "crawl_error": "dataforseo_crawl module not available"}

    result["crawl_ran"] = crawl.get("crawl_ran", False)
    result["crawl_error"] = crawl.get("crawl_error")
    if crawl.get("crawl_ran"):
        result["pages_crawled"] = crawl.get("pages_crawled")
        result["broken_internal_urls"] = crawl.get("broken_internal_urls")
        result["https_to_http_links"] = crawl.get("https_to_http_links")
        result["redirect_pages"] = crawl.get("redirect_pages")
        result["permanent_redirects"] = crawl.get("permanent_redirects")
        result["temporary_redirects"] = crawl.get("temporary_redirects")
        result["missing_title_pages"] = crawl.get("missing_title")
        result["short_title_pages"] = crawl.get("short_title")
        result["long_title_pages"] = crawl.get("long_title")
        result["duplicate_title_pages"] = crawl.get("duplicate_titles")
        result["missing_meta_descriptions"] = crawl.get("missing_meta_descriptions")
        result["duplicate_meta_pages"] = crawl.get("duplicate_meta_descriptions")
        result["missing_h1_pages"] = crawl.get("missing_h1")
        result["multiple_h1_pages"] = crawl.get("multiple_h1")
        result["h1_duplicates_title_pages"] = crawl.get("h1_duplicates_title")
        result["missing_canonical_pages"] = crawl.get("missing_canonical")
        result["pages_without_hreflang"] = crawl.get("pages_without_hreflang")
        result["pages_hreflang_no_self"] = crawl.get("pages_hreflang_no_self")
        result["images_missing_alt"] = crawl.get("pages_with_missing_alt")
        result["broken_internal_links"] = crawl.get("broken_internal_links")
        result["thin_content_pages"] = crawl.get("thin_content_pages")
        result["avg_word_count"] = crawl.get("avg_word_count")
        result["avg_text_to_html_ratio"] = crawl.get("avg_text_to_html_ratio")
        result["empty_anchor_links_total"] = crawl.get("empty_anchor_links_total")
        result["max_crawl_depth"] = crawl.get("max_crawl_depth")
        result["avg_crawl_depth"] = crawl.get("avg_crawl_depth")
        result["pages_deep_crawl"] = crawl.get("pages_deep_crawl")
        result["sitemap_urls_count"] = crawl.get("sitemap_urls_count")
        result["orphan_pages"] = crawl.get("orphan_pages")
        result["crawl_scope_note"] = crawl.get("crawl_scope_note")
        # DataForSEO extras — override SEMrush defaults when crawl provides data
        if crawl.get("site_health_score") is not None:
            result["site_health_score"] = crawl["site_health_score"]
        if crawl.get("duplicate_content_pages") is not None:
            result["duplicate_content_pages"] = crawl["duplicate_content_pages"]
        result["broken_resources_pages"] = crawl.get("broken_resources_pages")
        result["dataforseo_task_id"] = crawl.get("dataforseo_task_id")

    print(
        f"[p2] Website health gather complete. "
        f"Pages tested: {result['pages_tested']}, "
        f"Crawled: {result.get('pages_crawled') or 0}, "
        f"SEMrush: {'yes' if semrush_data else 'no'}"
    )
    return result


# ---------------------------------------------------------------------------
# Site crawl - lightweight BFS (requests + BeautifulSoup)
# ---------------------------------------------------------------------------

_CRAWL_SKIP_EXTENSIONS = frozenset({
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".zip", ".tar", ".gz", ".exe", ".dmg", ".pkg",
    ".mp4", ".mp3", ".wav", ".avi", ".mov", ".webm",
    ".css", ".js", ".json", ".xml",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
})


def _strip_www(netloc: str) -> str:
    s = netloc.lower()
    return s[4:] if s.startswith("www.") else s


def _resolve_url(href: str, current: str, base_netloc: str) -> Optional[str]:
    """Resolve href to an absolute normalized internal URL, or None if it should be skipped."""
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return None
    try:
        absolute = urljoin(current, href)
        if "#" in absolute:
            absolute = absolute[: absolute.index("#")]
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            return None
        if _strip_www(parsed.netloc) != _strip_www(base_netloc):
            return None
        if os.path.splitext(parsed.path.lower())[1] in _CRAWL_SKIP_EXTENSIONS:
            return None
        # Normalize: strip trailing slash except for root path
        if parsed.path not in ("", "/") and absolute.endswith("/"):
            absolute = absolute.rstrip("/")
        return absolute
    except Exception:
        return None


def _fetch_sitemap_urls(base_url: str) -> set:
    """
    Fetch and parse /sitemap.xml, returning a normalized set of page URLs.
    Handles sitemap index files one level deep.
    Returns an empty set if the sitemap is missing or unparseable.
    """
    import xml.etree.ElementTree as ET

    parsed = urlparse(base_url)
    sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"

    def _parse_xml(text: str):
        page_urls: set = set()
        sub_sitemaps: List[str] = []
        try:
            root = ET.fromstring(text)
            ns_match = re.match(r"\{[^}]+\}", root.tag)
            ns = ns_match.group(0) if ns_match else ""
            tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
            if tag.lower() == "sitemapindex":
                for sm in root.findall(f"{ns}sitemap"):
                    loc = sm.find(f"{ns}loc")
                    if loc is not None and loc.text:
                        sub_sitemaps.append(loc.text.strip())
            else:
                for url_elem in root.findall(f"{ns}url"):
                    loc = url_elem.find(f"{ns}loc")
                    if loc is not None and loc.text:
                        page_urls.add(loc.text.strip().rstrip("/"))
        except ET.ParseError:
            pass
        return page_urls, sub_sitemaps

    urls: set = set()
    try:
        resp = requests.get(sitemap_url, timeout=_HTTP_TIMEOUT, headers=_HEADERS)
        if resp.status_code != 200:
            return urls
        page_urls, sub_sitemaps = _parse_xml(resp.text)
        urls.update(page_urls)
        for sub_url in sub_sitemaps[:10]:  # cap at 10 sub-sitemaps
            try:
                sub_resp = requests.get(sub_url, timeout=_HTTP_TIMEOUT, headers=_HEADERS)
                if sub_resp.status_code == 200:
                    sub_urls, _ = _parse_xml(sub_resp.text)
                    urls.update(sub_urls)
            except Exception:
                pass
    except Exception:
        pass
    return urls


def _crawl_get(
    url: str,
    method: str = "GET",
    stream: bool = False,
) -> requests.Response:
    """
    HTTP GET/HEAD with retry and exponential backoff.
    - 429 (rate-limited): waits 5s, 10s, 20s before each retry.
    - Timeout / connection error: waits 2s, 4s before each retry.
    Raises requests.exceptions.RequestException after all retries are exhausted.
    """
    kwargs: dict = {"timeout": _HTTP_TIMEOUT, "allow_redirects": True, "headers": _HEADERS}
    if stream:
        kwargs["stream"] = True
    fn = requests.head if method == "HEAD" else requests.get
    last_exc: Optional[Exception] = None
    for attempt in range(_CRAWL_MAX_RETRIES):
        try:
            resp = fn(url, **kwargs)
            if resp.status_code == 429 and attempt < _CRAWL_MAX_RETRIES - 1:
                wait = _CRAWL_BACKOFF_429 * (2 ** attempt)
                print(f"[crawl] 429 rate-limited, retrying in {wait}s: {url}")
                time.sleep(wait)
                continue
            if resp.status_code >= 500 and attempt < _CRAWL_MAX_RETRIES - 1:
                time.sleep(_CRAWL_BACKOFF_ERR * (2 ** attempt))
                continue
            return resp
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt < _CRAWL_MAX_RETRIES - 1:
                time.sleep(_CRAWL_BACKOFF_ERR * (2 ** attempt))
    raise last_exc or requests.exceptions.RequestException(f"Failed after retries: {url}")


def gather_site_crawl_facts(url: str, max_pages: int = 100) -> dict:
    """
    BFS crawler: visits up to max_pages internal pages and collects site-wide
    health signals comparable to a SEMrush site audit.

    Detects per-page: titles, meta descriptions, H1s, canonical tags,
    hreflang self-references, images missing alt, word count, text-to-HTML
    ratio, empty anchor links, HTTP status codes, and crawl depth.
    Also detects orphan pages (reachable by crawl but absent from sitemap).

    Requires: beautifulsoup4 (pip install beautifulsoup4)
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("[crawl] beautifulsoup4 not installed — skipping site crawl.")
        return {
            "crawl_ran": False,
            "crawl_error": "beautifulsoup4 not installed (pip install beautifulsoup4)",
            "pages_crawled": 0,
        }

    base_netloc = urlparse(url).netloc
    is_https_site = url.startswith("https://")
    result = {
        "crawl_ran": False,
        "crawl_error": None,
        "pages_crawled": 0,
        "crawl_errors": 0,          # pages that failed to load during crawl
        "broken_internal_links": 0, # link occurrences pointing to 4xx/5xx internal pages
        "broken_internal_urls": 0,  # unique count of broken internal URLs
        "https_to_http_links": 0,   # internal links using http:// on an https site
        "redirect_pages": 0,
        "permanent_redirects": 0,    # 301
        "temporary_redirects": 0,    # 302
        "missing_title": 0,
        "short_title": 0,
        "long_title": 0,
        "duplicate_titles": 0,
        "missing_meta_descriptions": 0,
        "duplicate_meta_descriptions": 0,
        "missing_h1": 0,
        "multiple_h1": 0,
        "h1_duplicates_title": 0,
        "missing_canonical": 0,
        "pages_without_hreflang": 0,
        "pages_hreflang_no_self": 0,
        "images_missing_alt_total": 0,
        "pages_with_missing_alt": 0,
        "avg_word_count": None,
        "thin_content_pages": 0,
        "avg_text_to_html_ratio": None,
        "empty_anchor_links_total": 0,
        # Depth metrics
        "max_crawl_depth": None,
        "avg_crawl_depth": None,
        "pages_deep_crawl": 0,          # pages at click depth > 3
        # Orphan detection
        "sitemap_urls_count": None,
        "orphan_pages": None,           # crawlable but absent from sitemap
        # Scope note for downstream consumers (e.g. GPT prompt)
        "crawl_scope_note": None,
    }

    queue: deque = deque([(url, 0)])    # (url, depth)
    visited: set = set()
    enqueued: set = {url.rstrip("/")}
    status_by_url: Dict[str, int] = {}   # normalized_url → HTTP status (0 = connection error)
    link_targets: Dict[str, List[str]] = {}  # normalized_target → [source_url, ...]
    depth_by_url: Dict[str, int] = {}    # normalized_url → click depth from homepage
    crawled_html_urls: set = set()       # URLs where HTML was successfully parsed
    titles: Counter = Counter()
    metas: Counter = Counter()
    word_counts: List[int] = []
    html_ratios: List[float] = []

    try:
        while queue and len(visited) < max_pages:
            current, depth = queue.popleft()
            normalized = current.rstrip("/")
            if normalized in visited:
                continue
            visited.add(normalized)
            depth_by_url[normalized] = depth

            try:
                resp = _crawl_get(current)
            except Exception:
                result["crawl_errors"] += 1
                status_by_url[normalized] = 0
                continue

            status_by_url[normalized] = resp.status_code
            # Also record the final URL if redirected
            if resp.history:
                result["redirect_pages"] += 1
                # Use last hop — that's the redirect that matters for SEO
                # (e.g. http→301→https→302→canonical: the 302 is the problem)
                last_hop_status = resp.history[-1].status_code
                if last_hop_status == 301:
                    result["permanent_redirects"] += 1
                elif last_hop_status == 302:
                    result["temporary_redirects"] += 1
                final_key = resp.url.rstrip("/")
                visited.add(final_key)
                status_by_url[final_key] = resp.status_code

            if resp.status_code >= 400:
                result["crawl_errors"] += 1
                continue

            if "text/html" not in resp.headers.get("Content-Type", "").lower():
                continue

            raw_html = resp.text
            soup = BeautifulSoup(raw_html, "html.parser")
            result["pages_crawled"] += 1
            crawled_html_urls.add(normalized)

            # Title
            title_tag = soup.find("title")
            title_text = title_tag.get_text().strip() if title_tag else ""
            if not title_text:
                result["missing_title"] += 1
            else:
                if len(title_text) < 30:
                    result["short_title"] += 1
                elif len(title_text) > 60:
                    result["long_title"] += 1
                titles[title_text.lower()] += 1

            # Meta description
            meta_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
            meta_content = (meta_tag.get("content", "") or "").strip() if meta_tag else ""
            if not meta_content:
                result["missing_meta_descriptions"] += 1
            else:
                metas[meta_content.lower()] += 1

            # H1
            h1_tags = soup.find_all("h1")
            h1_texts = [h.get_text(strip=True) for h in h1_tags]
            if len(h1_tags) == 0:
                result["missing_h1"] += 1
            elif len(h1_tags) > 1:
                result["multiple_h1"] += 1
            if h1_texts and title_text and h1_texts[0].lower() == title_text.lower():
                result["h1_duplicates_title"] += 1

            # Canonical
            canonical_tag = soup.find("link", rel=re.compile(r"canonical", re.I))
            if not canonical_tag or not canonical_tag.get("href"):
                result["missing_canonical"] += 1

            # Hreflang self-reference
            hreflang_tags = [
                t for t in soup.find_all("link", rel=True)
                if "alternate" in (t.get("rel") or []) and t.get("hreflang")
            ]
            if not hreflang_tags:
                result["pages_without_hreflang"] += 1
            else:
                current_norm = resp.url.rstrip("/")
                has_self = any(
                    t.get("href", "").rstrip("/") == current_norm
                    for t in hreflang_tags
                )
                if not has_self:
                    result["pages_hreflang_no_self"] += 1

            # Images missing alt
            missing_alt = sum(
                1 for img in soup.find_all("img")
                if not img.get("alt", "").strip()
            )
            result["images_missing_alt_total"] += missing_alt
            if missing_alt > 0:
                result["pages_with_missing_alt"] += 1

            # Word count + text-to-HTML ratio
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            page_text = soup.get_text(separator=" ")
            word_count = len(page_text.split())
            word_counts.append(word_count)
            if word_count < 300:
                result["thin_content_pages"] += 1
            if raw_html:
                html_ratios.append(len(page_text) / max(len(raw_html), 1))

            # Single pass over all anchors:
            # empty anchor detection + link target recording + https_to_http + queue
            for a in soup.find_all("a", href=True):
                href = a["href"]

                # Empty anchor: no visible text and no alt on inner image
                if not a.get_text(strip=True):
                    img_inside = a.find("img")
                    if not img_inside or not img_inside.get("alt", "").strip():
                        result["empty_anchor_links_total"] += 1

                resolved = _resolve_url(href, resp.url, base_netloc)
                if not resolved:
                    continue

                key = resolved.rstrip("/")

                # Explicit http:// link to the same domain on an https site
                if is_https_site and resolved.startswith("http://"):
                    result["https_to_http_links"] += 1

                # Record as a link target for broken-link detection
                if key not in link_targets:
                    link_targets[key] = []
                link_targets[key].append(resp.url)

                # Queue management
                if key not in visited and key not in enqueued:
                    enqueued.add(key)
                    queue.append((resolved, depth + 1))

        # HEAD-check any internal link targets we never visited during the crawl.
        # Cap at 200 checks to bound total time.
        unvisited = [
            (key, sources)
            for key, sources in link_targets.items()
            if key not in status_by_url
        ][:200]
        if unvisited:
            print(f"[crawl] Checking {len(unvisited)} unvisited link targets ...")
        for key, _ in unvisited:
            try:
                head = _crawl_get(key, method="HEAD")
                if head.status_code == 405:
                    # Server does not allow HEAD — fall back to GET with streaming
                    get = _crawl_get(key, stream=True)
                    get.close()
                    status_by_url[key] = get.status_code
                else:
                    status_by_url[key] = head.status_code
            except Exception:
                status_by_url[key] = 0

        # Compute broken internal link counts
        broken_keys = {k for k, s in status_by_url.items() if s == 0 or s >= 400}
        result["broken_internal_links"] = sum(
            len(sources)
            for key, sources in link_targets.items()
            if key in broken_keys
        )
        result["broken_internal_urls"] = sum(
            1 for key in link_targets if key in broken_keys
        )

        # Depth metrics
        if depth_by_url:
            depths = list(depth_by_url.values())
            result["max_crawl_depth"] = max(depths)
            result["avg_crawl_depth"] = round(sum(depths) / len(depths), 1)
            result["pages_deep_crawl"] = sum(1 for d in depths if d > 3)

        # Orphan detection — pages reachable by crawl but absent from sitemap
        sitemap_urls = _fetch_sitemap_urls(url)
        result["sitemap_urls_count"] = len(sitemap_urls) if sitemap_urls else None
        if sitemap_urls:
            sitemap_norm = {u.rstrip("/") for u in sitemap_urls}
            result["orphan_pages"] = sum(
                1 for u in crawled_html_urls if u not in sitemap_norm
            )

        # Aggregates — count affected pages, not distinct duplicate groups
        # e.g. 3 pages sharing the same title → duplicate_titles = 3, not 1
        result["duplicate_titles"] = sum(c for c in titles.values() if c > 1)
        result["duplicate_meta_descriptions"] = sum(c for c in metas.values() if c > 1)
        if word_counts:
            result["avg_word_count"] = round(sum(word_counts) / len(word_counts))
        if html_ratios:
            result["avg_text_to_html_ratio"] = round(
                sum(html_ratios) / len(html_ratios), 3
            )
        capped = len(visited) >= max_pages
        scope_note = f"BFS crawl, {result['pages_crawled']} HTML pages parsed (cap: {max_pages})."
        if capped:
            scope_note += " Cap reached; depth and orphan counts reflect the crawled sample only."
        scope_note += (
            " orphan_pages = pages reachable by crawl but absent from sitemap"
            " (not strictly SEO-orphaned; may include paginated/tag pages)."
        )
        result["crawl_scope_note"] = scope_note

        result["crawl_ran"] = True
        print(
            f"[crawl] Done. {result['pages_crawled']} pages crawled, "
            f"{result['broken_internal_links']} broken link occurrences "
            f"({result['broken_internal_urls']} unique URLs), "
            f"{result['missing_meta_descriptions']} missing meta descriptions."
        )
    except Exception as e:
        result["crawl_error"] = str(e)
        print(f"[crawl] ERROR: {e}")

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
