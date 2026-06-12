"""
Test for the Pillar 1 globalization gathering pipeline.

Usage:
  power/bin/python3 test_pillar1_gather.py <url>
  power/bin/python3 test_pillar1_gather.py <url> --crawl-only
  power/bin/python3 test_pillar1_gather.py <url> --mixed-only

Flags:
  --crawl-only    Only run the Playwright crawler (skip GPT mixed language check)
  --mixed-only    Only run the GPT mixed language check (skip crawler, requires --locales)
  --locales       Comma-separated locale:url pairs for --mixed-only mode
                  e.g. --locales "EN:https://example.com/en/,FR:https://example.com/fr/"

Requires OPENAI_API_KEY in backend/.env
"""

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
from pillar1_gather import gather_pillar1_facts, gather_mixed_language_issues


def parse_args():
    args = sys.argv[1:]
    url = None
    crawl_only = "--crawl-only" in args
    mixed_only = "--mixed-only" in args
    locale_urls = {}

    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("http"):
            url = a
        elif a == "--locales" and i + 1 < len(args):
            for pair in args[i + 1].split(","):
                pair = pair.strip()
                if ":" in pair:
                    lang, _, lurl = pair.partition(":")
                    locale_urls[lang.strip().upper()] = lurl.strip()
            i += 1
        i += 1

    return url, crawl_only, mixed_only, locale_urls


def print_crawl_result(result: dict):
    print("\n" + "=" * 60)
    print("PILLAR 1 — CRAWLER RESULTS")
    print("=" * 60)

    def row(label, value):
        print(f"  {label:<40} {value}")

    row("Crawler ran", result.get("crawler_ran"))
    if result.get("crawler_error"):
        print(f"  ERROR: {result['crawler_error']}")
        return

    print("\n[Languages]")
    row("Available languages", result.get("available_languages"))
    row("Language variants", result.get("available_language_variants"))
    row("Language selector type", result.get("language_selector_type"))

    locale_urls = result.get("locale_urls", {})
    if locale_urls:
        print(f"\n[Locale URLs] ({len(locale_urls)} found)")
        for lang, url in locale_urls.items():
            print(f"    {lang}: {url}")

    print("\n[Hreflang]")
    row("Hreflang present", result.get("hreflang_present"))
    row("Hreflang tags", len(result.get("hreflang_tags", [])))
    row("x-default present", result.get("hreflang_x_default_present"))
    row("x-default URL", result.get("hreflang_x_default_url"))

    print("\n[Cookie Consent]")
    detected = result.get("cookie_banner_detected")
    provider = result.get("cookie_provider")
    if detected is None:
        row("Cookie banner", "not checked")
    elif detected:
        row("Cookie banner detected", f"YES — provider: {provider or 'unknown'}")
    else:
        row("Cookie banner detected", "NO")

    ml_issues = result.get("mixed_language_issues", [])
    print(f"\n[Mixed Language Issues] ({len(ml_issues)} locales affected)")
    for issue in ml_issues:
        print(f"  Locale {issue.get('locale')} ({issue.get('page_url')})")
        for hit in issue.get("language_hits", []):
            print(f"    {hit.get('language')}: {hit.get('marker_strings_found')}")


def print_mixed_result(issues: list):
    print("\n" + "=" * 60)
    print("GPT-5 MIXED LANGUAGE CHECK RESULTS")
    print("=" * 60)

    if not issues:
        print("  No mixed-language issues found.")
        return

    print(f"  {len(issues)} locale(s) with issues:\n")
    for issue in issues:
        print(f"  Locale: {issue.get('locale')}  ({issue.get('page_url')})")
        for hit in issue.get("language_hits", []):
            print(f"    Language leaking in: {hit.get('language')}")
            for s in hit.get("marker_strings_found", []):
                print(f"      - {s!r}")
        print()

    print("FULL JSON:")
    print(json.dumps(issues, indent=2, ensure_ascii=False))


def main():
    url, crawl_only, mixed_only, locale_urls = parse_args()

    if not url and not mixed_only:
        print("Usage: python test_pillar1_gather.py <url> [--crawl-only] [--mixed-only] [--locales ...]")
        sys.exit(1)

    if mixed_only:
        if not locale_urls:
            print("--mixed-only requires --locales. Example:")
            print('  --locales "EN:https://example.com/en/,FR:https://example.com/fr/"')
            sys.exit(1)
        print(f"\nRunning GPT-5 mixed language check on {len(locale_urls)} locale(s)...")
        issues = gather_mixed_language_issues(url or "", locale_urls)
        print_mixed_result(issues)
        return

    # Full run or crawl-only
    print(f"\nURL: {url}")
    print("\nStep 1: Running Playwright crawler...")
    crawl_result = gather_pillar1_facts(url)
    print_crawl_result(crawl_result)

    if crawl_only:
        return

    if not crawl_result.get("crawler_ran"):
        print("\nCrawler did not run — skipping GPT mixed language check.")
        return

    found_locales = crawl_result.get("locale_urls", {})
    if not found_locales:
        print("\nNo locale URLs found — skipping GPT mixed language check.")
        return

    print(f"\nStep 2: Running GPT-5 mixed language check on {len(found_locales)} locale(s)...")
    issues = gather_mixed_language_issues(url, found_locales)
    print_mixed_result(issues)


if __name__ == "__main__":
    main()
