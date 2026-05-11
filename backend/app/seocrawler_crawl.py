"""
Pillar 2 site crawl using the built-in SEO-Crawler (replaces DataForSEO OnPage API).

Calls run_crawl() from SEO-Crawler/crawler.py, collects per-page results,
and aggregates them into the same dict shape that dataforseo_crawl returned —
so website_health.py requires no field remapping.

Fields that cannot be computed without modifying crawler.py are returned as None:
  max/avg_crawl_depth, avg_text_to_html_ratio, broken_external_links,
  broken_resources_pages, duplicate_content_pages, https_to_http_links,
  pages_hreflang_no_self, empty_anchor_links_total.
"""

import asyncio
import sys
from pathlib import Path

_CRAWLER_DIR = Path(__file__).resolve().parent.parent.parent / "SEO-Crawler"
if str(_CRAWLER_DIR) not in sys.path:
    sys.path.insert(0, str(_CRAWLER_DIR))

from crawler import run_crawl  # noqa: E402  (path inserted above)

_ERROR_ISSUES = frozenset({
    "missing_title",
    "missing_meta_description",
    "missing_h1",
    "missing_canonical",
    "html_lang_mismatch",
    "title_lang_mismatch",
})
_WARNING_ISSUES = frozenset({
    "title_too_short", "title_too_long",
    "meta_desc_too_short", "meta_desc_too_long",
    "multiple_h1",
    "missing_hreflang", "missing_xdefault",
    "thin_content",
    "heading_skip",
    "missing_img_alt",
    "missing_og",
    "missing_html_lang",
    "canonical_cross_domain",
    "multiple_canonicals",
})


def _page_score(issues: list) -> int:
    """Per-page health score: 100 minus deductions (errors −10, warnings −3), floor 0."""
    errors = sum(1 for i in issues if i in _ERROR_ISSUES)
    warnings = sum(1 for i in issues if i in _WARNING_ISSUES)
    return max(0, 100 - errors * 10 - warnings * 3)


def gather_site_crawl_facts_seocrawler(url: str, max_pages: int = 200) -> dict:
    """
    Crawl url using SEO-Crawler and return aggregated site health stats.
    Returns the same field names as dataforseo_crawl.gather_site_crawl_facts_dataforseo().
    """
    results: list = []
    sitemap_urls: list = []

    def on_result(page_data: dict):
        results.append(page_data)

    def on_sitemap(count: int, urls: list):
        sitemap_urls.extend(urls)

    try:
        asyncio.run(run_crawl(
            start_url=url,
            max_pages=max_pages,
            on_result=on_result,
            on_sitemap=on_sitemap,
        ))
    except Exception as e:
        print(f"[seocrawler] Crawl failed: {e}")
        return {"crawl_ran": False, "crawl_error": str(e)[:500]}

    if not results:
        return {"crawl_ran": False, "crawl_error": "No pages crawled"}

    total = len(results)
    ok_pages = [r for r in results if 200 <= r.get("http_status", 0) < 300]

    def count_issue(key: str) -> int:
        return sum(1 for r in results if key in r.get("issues", []))

    # Duplicate title detection
    title_freq: dict = {}
    for r in ok_pages:
        t = r.get("title", "").strip()
        if t:
            title_freq[t] = title_freq.get(t, 0) + 1
    duplicate_titles = sum(1 for c in title_freq.values() if c > 1)

    # Duplicate meta description detection
    meta_freq: dict = {}
    for r in ok_pages:
        m = r.get("meta_description", "").strip()
        if m:
            meta_freq[m] = meta_freq.get(m, 0) + 1
    duplicate_meta_descriptions = sum(1 for c in meta_freq.values() if c > 1)

    # H1 duplicates title (case-insensitive)
    h1_duplicates_title = sum(
        1 for r in ok_pages
        if r.get("h1", "").strip() and r.get("title", "").strip()
        and r["h1"].strip().lower() == r["title"].strip().lower()
    )

    # Broken pages (4xx / 5xx)
    broken = [r for r in results if 400 <= r.get("http_status", 0) < 600]

    # Redirects
    redirects = [r for r in results if r.get("http_status", 0) in (301, 302, 307, 308)]
    permanent_redirects = sum(1 for r in redirects if r.get("http_status") in (301, 308))
    temporary_redirects = sum(1 for r in redirects if r.get("http_status") in (302, 307))

    # Slow pages (> 3 s)
    pages_slow_load = sum(1 for r in results if r.get("load_time_ms", 0) > 3000)

    # Orphan pages — in sitemap but not reached by crawl
    visited = {r["url"] for r in results}
    orphan_pages = len(set(sitemap_urls) - visited) if sitemap_urls else None

    # Average word count (successful pages only)
    wcs = [r["word_count"] for r in ok_pages if r.get("word_count")]
    avg_word_count = round(sum(wcs) / len(wcs)) if wcs else None

    # Site health score — average per-page score across successful pages
    scores = [_page_score(r.get("issues", [])) for r in ok_pages]
    site_health_score = round(sum(scores) / len(scores)) if scores else None

    # Aggregate issue severity counts
    errors_total = sum(
        sum(1 for i in r.get("issues", []) if i in _ERROR_ISSUES)
        for r in results
    )
    warnings_total = sum(
        sum(1 for i in r.get("issues", []) if i in _WARNING_ISSUES)
        for r in results
    )

    return {
        "crawl_ran": True,
        "crawl_error": None,
        "pages_crawled": total,
        "site_health_score": site_health_score,
        "errors_total": errors_total,
        "warnings_total": warnings_total,
        "notices_total": None,
        "broken_internal_urls": len(broken),
        "broken_internal_links": len(broken),
        "broken_external_links": None,
        "redirect_pages": len(redirects),
        "permanent_redirects": permanent_redirects,
        "temporary_redirects": temporary_redirects,
        "https_to_http_links": None,
        "missing_title": count_issue("missing_title"),
        "short_title": count_issue("title_too_short"),
        "long_title": count_issue("title_too_long"),
        "duplicate_titles": duplicate_titles,
        "missing_meta_descriptions": count_issue("missing_meta_description"),
        "duplicate_meta_descriptions": duplicate_meta_descriptions,
        "missing_h1": count_issue("missing_h1"),
        "multiple_h1": count_issue("multiple_h1"),
        "h1_duplicates_title": h1_duplicates_title,
        "missing_canonical": count_issue("missing_canonical"),
        "pages_without_hreflang": count_issue("missing_hreflang"),
        "pages_hreflang_no_self": None,
        "pages_with_missing_alt": sum(1 for r in results if r.get("images_without_alt", 0) > 0),
        "thin_content_pages": count_issue("thin_content"),
        "avg_word_count": avg_word_count,
        "avg_text_to_html_ratio": None,
        "empty_anchor_links_total": None,
        "max_crawl_depth": None,
        "avg_crawl_depth": None,
        "pages_deep_crawl": None,
        "sitemap_urls_count": len(sitemap_urls),
        "orphan_pages": orphan_pages,
        "pages_slow_load": pages_slow_load,
        "duplicate_content_pages": None,
        "broken_resources_pages": None,
        "hreflang_conflicts": None,
        "hreflang_language_mismatch": count_issue("html_lang_mismatch"),
        "unminified_js_css": None,
        "dataforseo_task_id": None,
        "crawl_scope_note": f"Crawled via SEO-Crawler (Playwright), up to {max_pages} pages",
    }
