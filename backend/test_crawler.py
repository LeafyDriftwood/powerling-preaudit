"""
Quick test for the Pillar 1 Playwright crawler.
Run from the backend/ directory:
    power/bin/python3 test_crawler.py https://www.example.com
"""
import sys
import json
from app.crawler import gather_pillar1_facts

url = sys.argv[1] if len(sys.argv) > 1 else "https://www.oxypharm.net"

print(f"\n{'='*60}")
print(f"  Crawling: {url}")
print(f"{'='*60}\n")

result = gather_pillar1_facts(url)

print(f"\n{'='*60}")
print("  RESULTS")
print(f"{'='*60}\n")

print(f"Crawler ran:          {result['crawler_ran']}")
if result['crawler_error']:
    print(f"Crawler error:        {result['crawler_error']}")

print(f"hreflang present:     {result['hreflang_present']}")
print(f"Language selector:    {result['language_selector_type']}")
print(f"Available languages:  {result['available_languages']}")
print(f"Pages checked:        {result['pages_checked']}")

print(f"\nLocale URLs ({len(result['locale_urls'])}):")
for lang, href in result['locale_urls'].items():
    print(f"  {lang}: {href}")

if result['hreflang_tags']:
    print(f"\nhreflang tags ({len(result['hreflang_tags'])}):")
    for tag in result['hreflang_tags']:
        print(f"  {tag['lang']}: {tag['href']}")

if result['mixed_language_issues']:
    print(f"\nMixed-language issues ({len(result['mixed_language_issues'])}):")
    for issue in result['mixed_language_issues']:
        print(f"  Locale {issue['locale']} ({issue['page_url']}):")
        if issue.get('language_hits'):
            for hit in issue['language_hits']:
                print(f"    [{hit['language']}] markers:")
                for s in hit.get('marker_strings_found', []):
                    print(f"      - \"{s}\"")
        else:
            for s in issue.get('french_strings_found', []):
                print(f"    - \"{s}\"")
else:
    print("\nNo mixed-language issues found.")

print(f"\n--- Full JSON ---")
print(json.dumps(result, indent=2, ensure_ascii=False))
