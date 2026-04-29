"""
DataForSEO OnPage API — site crawl for Powerling Pre-Audit Pillar 2.

Returns a dict with the same field names as gather_site_crawl_facts() in
website_health.py so it can be used as a drop-in replacement.

Pricing (pay-as-you-go, charged only for pages actually crawled):
  basic only:          $0.000125/page  — all SEO fields, status codes
  + load_resources:    $0.000375/page  — also detects broken images/CSS/scripts
  + enable_javascript: $0.001250/page  — renders JS (React/Vue/Next CSR sites)

Auth: HTTP Basic Auth
  Set DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD in backend/.env

Docs: https://docs.dataforseo.com/v3/on_page/overview/
"""

import os
import time
from urllib.parse import urlparse

import requests

_BASE = "https://api.dataforseo.com/v3/on_page"
_POLL_INTERVAL = 15    # seconds between summary polls
_POLL_TIMEOUT = 1800   # give up after 30 min (large sites need 15-20 min)
_PAGES_BATCH = 100     # DataForSEO max items per pages request
_HTTP_TIMEOUT = 30
_MAX_RETRIES = 3
_BACKOFF_429 = 5       # seconds; doubles each retry (5, 10, 20)
_BACKOFF_ERR = 2       # seconds for transient errors; doubles each retry


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    login = os.environ.get("DATAFORSEO_LOGIN", "")
    password = os.environ.get("DATAFORSEO_PASSWORD", "")
    if not login or not password:
        raise EnvironmentError(
            "DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD must be set in .env"
        )
    s = requests.Session()
    s.auth = (login, password)
    s.headers.update({"Content-Type": "application/json"})
    return s


def _dig(obj, *keys, default=None):
    """Safely traverse nested dicts/lists by key or integer index."""
    for k in keys:
        if obj is None:
            return default
        if isinstance(obj, list):
            try:
                obj = obj[k]
            except (IndexError, TypeError):
                return default
        elif isinstance(obj, dict):
            obj = obj.get(k)
        else:
            return default
    return obj if obj is not None else default


def _request(session: requests.Session, method: str, url: str, **kwargs) -> dict:
    """
    HTTP GET or POST with retry/backoff and DataForSEO JSON status validation.
    - 429: waits 5s, 10s, 20s before each retry.
    - Transient errors: waits 2s, 4s before each retry.
    - Validates JSON-level status_code on success (DataForSEO returns 200 HTTP
      even for application-level errors; status_code 20000 = OK).
    Returns the parsed JSON dict.
    """
    fn = session.get if method == "GET" else session.post
    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = fn(url, timeout=_HTTP_TIMEOUT, **kwargs)
            if resp.status_code == 429 and attempt < _MAX_RETRIES - 1:
                wait = _BACKOFF_429 * (2 ** attempt)
                print(f"[dfseo] 429 rate-limited, retrying in {wait}s ...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            # Validate DataForSEO application-level status
            api_status = data.get("status_code")
            if api_status is not None and api_status != 20000:
                raise RuntimeError(
                    f"DataForSEO error {api_status}: {data.get('status_message')}"
                )
            return data
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_BACKOFF_ERR * (2 ** attempt))
    raise last_exc or RuntimeError(f"Request failed after {_MAX_RETRIES} attempts: {url}")


def _summary_check(summary_result: dict, key: str, default=None):
    """
    Extract an aggregate count from a DataForSEO summary result.
    Counts live either directly in page_metrics or in page_metrics.checks
    depending on the field — try both.
    """
    pm = summary_result.get("page_metrics", {})
    if key in pm:
        return pm[key]
    checks = pm.get("checks", {})
    return checks.get(key, default)


def _cost_estimate(max_pages: int, enable_javascript: bool, load_resources: bool) -> float:
    basic = 0.000125
    factor = 1
    if enable_javascript:
        factor += 9
    elif load_resources:
        factor += 2
    return max_pages * basic * factor


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def gather_site_crawl_facts_dataforseo(
    url: str,
    max_pages: int = 200,
    enable_javascript: bool = False,
    load_resources: bool = False,
) -> dict:
    """
    Run a DataForSEO OnPage crawl and return a dict matching the schema of
    gather_site_crawl_facts() so it can be swapped in without changing
    the rest of the Pillar 2 pipeline.

    Fields not available from DataForSEO (left as None):
      - empty_anchor_links_total  (not tracked by DataForSEO)
      - h1_duplicates_title       (requires per-page H1 vs title comparison)
      - pages_without_hreflang    (no hreflang check in pages endpoint checks dict)
      - pages_hreflang_no_self    (requires links endpoint — future)
      - images_missing_alt_total  (DataForSEO gives page count, not image count)
      - sitemap_urls_count        (DataForSEO doesn't expose raw sitemap size)
      - permanent/temporary_redirects split (DataForSEO reports final status 200,
        not original 301/302; split requires redirect_chains endpoint — future)

    Note on orphan_pages:
      DataForSEO defines is_orphan_page as pages with no internal links pointing
      to them. Current implementation counts this from per-page checks.is_orphan_page.
      The summary page_metrics.checks may also expose is_orphan_page as an aggregate —
      if so, that would be simpler and consistent with how other fields are computed.
      See PROJECT.md for the pending verification task.

    Extra fields added by DataForSEO (not in built-in crawler):
      - site_health_score         (0–100 onpage_score)
      - duplicate_content_pages   (near-duplicate content detection)
      - broken_resources_pages    (pages with broken images/CSS/JS, load_resources=True)
      - dataforseo_task_id
    """
    result = {
        # Standard schema (matches gather_site_crawl_facts output)
        "crawl_ran": False,
        "crawl_error": None,
        "pages_crawled": 0,
        "crawl_errors": 0,
        "broken_internal_links": None,   # occurrence count unavailable from summary;
                                         # falls back to broken_internal_urls below
        "broken_internal_urls": None,    # unique broken URL count
        "https_to_http_links": None,
        "redirect_pages": None,          # all redirects (301 + 302 + other)
        "permanent_redirects": None,     # 301 only
        "temporary_redirects": None,     # 302 only
        "missing_title": None,
        "short_title": None,
        "long_title": None,
        "duplicate_titles": None,
        "missing_meta_descriptions": None,
        "duplicate_meta_descriptions": None,
        "missing_h1": None,
        "multiple_h1": None,
        "h1_duplicates_title": None,
        "missing_canonical": None,
        "pages_without_hreflang": None,
        "pages_hreflang_no_self": None,  # not available
        "images_missing_alt_total": None,
        "pages_with_missing_alt": None,
        "avg_word_count": None,
        "thin_content_pages": None,
        "avg_text_to_html_ratio": None,
        "empty_anchor_links_total": None,  # not available
        "max_crawl_depth": None,
        "avg_crawl_depth": None,
        "pages_deep_crawl": None,
        "sitemap_urls_count": None,        # not available
        "orphan_pages": None,              # pages with no inbound internal links — see docstring
        "crawl_scope_note": None,
        # DataForSEO extras
        "site_health_score": None,
        "duplicate_content_pages": None,
        "broken_resources_pages": None,
        "dataforseo_task_id": None,
    }

    try:
        parsed = urlparse(url)
        target = parsed.netloc  # e.g. "example.com" — no protocol, no path

        session = _session()

        # ----------------------------------------------------------------
        # 1. Create crawl task
        # ----------------------------------------------------------------
        est = _cost_estimate(max_pages, enable_javascript, load_resources)
        print(
            f"[dfseo] Starting OnPage crawl: {target} "
            f"(max {max_pages} pages, est. ${est:.4f}) ..."
        )

        payload = [{
            "target": target,
            "max_crawl_pages": max_pages,
            "enable_javascript": enable_javascript,
            "load_resources": load_resources,
            "crawl_delay": 100,
            "store_raw_html": False,
            "check_spell": False,
        }]

        task_data = _request(session, "POST", f"{_BASE}/task_post", json=payload)
        task_id = _dig(task_data, "tasks", 0, "id")
        if not task_id:
            raise RuntimeError("No task_id in task_post response.")

        result["dataforseo_task_id"] = task_id
        print(f"[dfseo] Task created: {task_id}")

        # ----------------------------------------------------------------
        # 2. Poll until finished
        # ----------------------------------------------------------------
        elapsed = 0
        summary_result = None

        while elapsed < _POLL_TIMEOUT:
            time.sleep(_POLL_INTERVAL)
            elapsed += _POLL_INTERVAL

            s_data = _request(session, "GET", f"{_BASE}/summary/{task_id}")
            summary_result = _dig(s_data, "tasks", 0, "result", 0)
            if not summary_result:
                print(f"[dfseo] No summary result yet ({elapsed}s elapsed) ...")
                continue

            progress = summary_result.get("crawl_progress", "")
            crawled = _dig(summary_result, "crawl_status", "pages_crawled") or 0
            in_queue = _dig(summary_result, "crawl_status", "pages_in_queue") or 0
            print(
                f"[dfseo] {progress} — crawled: {crawled}, in queue: {in_queue} "
                f"({elapsed}s elapsed)"
            )

            if progress == "finished":
                break

        partial = summary_result and summary_result.get("crawl_progress") != "finished"
        if not summary_result:
            raise TimeoutError(f"Crawl did not finish within {_POLL_TIMEOUT}s and no data was returned.")
        if partial:
            crawled_so_far = _dig(summary_result, "crawl_status", "pages_crawled") or 0
            print(f"[dfseo] Warning: crawl timed out after {_POLL_TIMEOUT}s. Using partial results ({crawled_so_far} pages crawled).")

        # ----------------------------------------------------------------
        # 3. Map summary aggregate counts
        # ----------------------------------------------------------------
        crawl_status = summary_result.get("crawl_status", {})
        result["pages_crawled"] = crawl_status.get("pages_crawled", 0)
        result["site_health_score"] = (
            summary_result.get("onpage_score")
            or _dig(summary_result, "page_metrics", "onpage_score")
        )

        # SEO issues
        result["missing_title"] = _summary_check(summary_result, "no_title", 0)
        result["short_title"] = _summary_check(summary_result, "title_too_short", 0)
        result["long_title"] = _summary_check(summary_result, "title_too_long", 0)
        result["duplicate_titles"] = _summary_check(summary_result, "duplicate_title", 0)
        result["missing_meta_descriptions"] = _summary_check(summary_result, "no_description", 0)
        result["duplicate_meta_descriptions"] = _summary_check(summary_result, "duplicate_description", 0)
        result["missing_h1"] = _summary_check(summary_result, "no_h1_tag", 0)
        result["pages_with_missing_alt"] = _summary_check(summary_result, "no_image_alt", 0)
        result["https_to_http_links"] = _summary_check(summary_result, "https_to_http_links", 0)
        result["thin_content_pages"] = _summary_check(summary_result, "low_content_rate", 0)
        result["duplicate_content_pages"] = _summary_check(summary_result, "duplicate_content", 0)

        # Link / crawl health
        result["broken_internal_urls"] = _summary_check(summary_result, "broken_links", 0)
        result["broken_resources_pages"] = _summary_check(summary_result, "broken_resources", 0)
        result["redirect_pages"] = _summary_check(summary_result, "is_redirect", 0)
        result["crawl_errors"] = _summary_check(summary_result, "is_broken", 0)
        # Try summary fields for redirect type split (may or may not exist)
        result["permanent_redirects"] = _summary_check(summary_result, "is_301")
        result["temporary_redirects"] = _summary_check(summary_result, "is_302")

        # broken_internal_links (occurrence count) is not in the summary.
        # Use broken_internal_urls as a fallback so downstream consumers get a number.
        result["broken_internal_links"] = result["broken_internal_urls"]

        # ----------------------------------------------------------------
        # 4. Fetch per-page data for fields not in summary:
        #    avg_word_count, avg_text_to_html_ratio, click_depth metrics,
        #    missing_canonical, multiple_h1, orphan_pages, hreflang
        # ----------------------------------------------------------------
        print(f"[dfseo] Fetching per-page data ...")

        word_counts = []
        text_ratios = []
        depths = []
        missing_canonical = 0
        multiple_h1 = 0
        h1_duplicates_title = 0
        orphan_count = 0
        permanent_redirects = 0
        temporary_redirects = 0
        offset = 0

        while True:
            p_data = _request(
                session, "POST", f"{_BASE}/pages",
                json=[{"id": task_id, "limit": _PAGES_BATCH, "offset": offset}],
            )

            items = _dig(p_data, "tasks", 0, "result", 0, "items") or []
            if not items:
                break

            for item in items:
                if item.get("resource_type") != "html":
                    continue

                meta = item.get("meta", {})
                checks = item.get("checks", {})
                content = meta.get("content", {})

                wc = content.get("plain_text_word_count")
                if wc is not None:
                    word_counts.append(wc)

                tr = content.get("plain_text_rate")
                if tr is not None:
                    text_ratios.append(tr)

                cd = item.get("click_depth")
                if cd is not None:
                    depths.append(cd)

                # checks.canonical == True means canonical IS present and valid
                if not checks.get("canonical", True):
                    missing_canonical += 1

                h1s = meta.get("htags", {}).get("h1", [])
                if len(h1s) > 1:
                    multiple_h1 += 1
                title_text = (meta.get("title") or "").strip().lower()
                if h1s and title_text and h1s[0].strip().lower() == title_text:
                    h1_duplicates_title += 1

                # DataForSEO has no per-page hreflang check in the checks dict;
                # pages_without_hreflang stays None (not computable from pages endpoint)

                # is_orphan_page is DataForSEO's native orphan signal (no inbound
                # internal links AND not in sitemap) — more accurate than from_sitemap alone
                if checks.get("is_orphan_page", False):
                    orphan_count += 1

                # Redirect type split — status_code on the item is the original
                # response code before following (301/302); fall back if not present
                sc = item.get("status_code")
                if sc == 301:
                    permanent_redirects += 1
                elif sc == 302:
                    temporary_redirects += 1

            offset += _PAGES_BATCH
            if len(items) < _PAGES_BATCH:
                break

        if word_counts:
            result["avg_word_count"] = round(sum(word_counts) / len(word_counts))
        if text_ratios:
            result["avg_text_to_html_ratio"] = round(
                sum(text_ratios) / len(text_ratios), 3
            )
        if depths:
            result["max_crawl_depth"] = max(depths)
            result["avg_crawl_depth"] = round(sum(depths) / len(depths), 1)
            result["pages_deep_crawl"] = sum(1 for d in depths if d > 3)

        result["missing_canonical"] = missing_canonical
        result["multiple_h1"] = multiple_h1
        result["h1_duplicates_title"] = h1_duplicates_title
        # pages_without_hreflang: not computable from DataForSEO pages endpoint
        result["orphan_pages"] = orphan_count
        # Use per-page counts as fallback if summary didn't have 301/302 fields
        if result["permanent_redirects"] is None:
            result["permanent_redirects"] = permanent_redirects
        if result["temporary_redirects"] is None:
            result["temporary_redirects"] = temporary_redirects

        # ----------------------------------------------------------------
        # 5. Scope note
        # ----------------------------------------------------------------
        capped = result["pages_crawled"] >= max_pages
        scope = (
            f"DataForSEO OnPage crawl, {result['pages_crawled']} pages "
            f"(cap: {max_pages})."
        )
        if partial:
            scope += " Crawl timed out; results reflect pages crawled before timeout."
        elif capped:
            scope += " Cap reached; depth counts reflect sample only."
        if enable_javascript:
            scope += " JS rendering enabled."
        scope += (
            " orphan_pages = pages with no inbound internal links (DataForSEO is_orphan_page)."
        )
        result["crawl_scope_note"] = scope

        result["crawl_ran"] = True
        print(
            f"[dfseo] Done. {result['pages_crawled']} pages, "
            f"health score: {result['site_health_score']}, "
            f"broken links: {result['broken_internal_urls']}, "
            f"missing meta: {result['missing_meta_descriptions']}."
        )

    except Exception as e:
        result["crawl_error"] = str(e)
        print(f"[dfseo] ERROR: {e}")

    return result
