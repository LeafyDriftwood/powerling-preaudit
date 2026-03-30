"""
Quick test for the DataForSEO OnPage crawl integration.

Usage:
  python test_dataforseo.py <url>
  python test_dataforseo.py <url> --pages 50
  python test_dataforseo.py <url> --js           # enable JS rendering
  python test_dataforseo.py <url> --load-resources

Requires DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD in backend/.env
"""

import argparse
import json
import os
import sys

# Load .env
env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))
from dataforseo_crawl import gather_site_crawl_facts_dataforseo, _cost_estimate


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("url", help="URL to crawl (e.g. https://example.com)")
    p.add_argument("--pages", type=int, default=50, help="Max pages to crawl (default 50)")
    p.add_argument("--js", action="store_true", help="Enable JavaScript rendering")
    p.add_argument("--load-resources", action="store_true", help="Load resources (broken image/CSS detection)")
    return p.parse_args()


def print_result(result: dict):
    print("\n" + "=" * 60)
    print("DATAFORSEO CRAWL RESULTS")
    print("=" * 60)

    def row(label, *keys):
        for k in keys:
            v = result.get(k)
            if v is not None:
                print(f"  {label:<40} {v}")
                return
        print(f"  {label:<40} —")

    print("\n[Crawl Status]")
    row("Crawl ran", "crawl_ran")
    row("Pages crawled", "pages_crawled")
    row("Crawl errors", "crawl_errors")
    row("Task ID", "dataforseo_task_id")
    if result.get("crawl_error"):
        print(f"  ERROR: {result['crawl_error']}")

    print("\n[Site Health]")
    row("OnPage health score (0-100)", "site_health_score")

    print("\n[Titles]")
    row("Missing title", "missing_title")
    row("Short title (< 30 chars)", "short_title")
    row("Long title (> 60 chars)", "long_title")
    row("Duplicate titles", "duplicate_titles")

    print("\n[Meta Descriptions]")
    row("Missing meta description", "missing_meta_descriptions")
    row("Duplicate meta descriptions", "duplicate_meta_descriptions")

    print("\n[H1 Tags]")
    row("Missing H1", "missing_h1")
    row("Multiple H1s", "multiple_h1")

    print("\n[Links & Redirects]")
    row("Broken internal URLs", "broken_internal_urls")
    row("Redirect pages", "redirect_pages")
    row("HTTPS → HTTP links", "https_to_http_links")

    print("\n[Images & Resources]")
    row("Pages with missing alt text", "pages_with_missing_alt")
    row("Broken resource pages", "broken_resources_pages")

    print("\n[Content]")
    row("Avg word count", "avg_word_count")
    row("Avg text-to-HTML ratio", "avg_text_to_html_ratio")
    row("Thin content pages (< 300 words)", "thin_content_pages")
    row("Duplicate content pages", "duplicate_content_pages")

    print("\n[Crawl Depth]")
    row("Max crawl depth", "max_crawl_depth")
    row("Avg crawl depth", "avg_crawl_depth")
    row("Pages at depth > 3", "pages_deep_crawl")

    print("\n[Technical]")
    row("Missing canonical", "missing_canonical")
    row("Pages without hreflang", "pages_without_hreflang")
    row("Orphan pages (not in sitemap)", "orphan_pages")

    if result.get("crawl_scope_note"):
        print(f"\n[Note] {result['crawl_scope_note']}")

    print("\n" + "=" * 60)
    print("RAW JSON (all fields):")
    # Exclude None fields for readability
    trimmed = {k: v for k, v in result.items() if v is not None and v != 0}
    print(json.dumps(trimmed, indent=2))


def main():
    args = parse_args()

    est = _cost_estimate(args.pages, args.js, args.load_resources)
    print(f"Estimated cost: ${est:.4f} for {args.pages} pages")
    print(f"URL: {args.url}")
    print(f"JS rendering: {'yes' if args.js else 'no'}")
    print(f"Load resources: {'yes' if args.load_resources else 'no'}")
    print()

    result = gather_site_crawl_facts_dataforseo(
        args.url,
        max_pages=args.pages,
        enable_javascript=args.js,
        load_resources=args.load_resources,
    )
    print_result(result)


if __name__ == "__main__":
    main()
