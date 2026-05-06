"""
Quick test for Pillar 2 website health checks (PSI + technical facts + site crawl).
Run from the backend/ directory:
    power/bin/python3 test_website_health.py https://www.example.com
    power/bin/python3 test_website_health.py https://www.example.com --competitor https://www.rival.com

Flags:
    --competitor <url>      Also run competitor PSI benchmark
    --locale <lang>=<url>   Add a locale URL to test (repeatable)
    --key <api_key>         Google PageSpeed Insights API key (optional)
    --tech-only             Skip PSI and crawl, only run technical checks
    --psi-only              Skip technical checks and crawl, only run PSI
    --crawl-only            Skip PSI and technical checks, only run site crawl
    --pages <n>             Max pages for site crawl (default: 100)
"""
import sys
import json
import os


def parse_args():
    args = sys.argv[1:]
    url = None
    competitor = None
    locale_urls = {}
    api_key = os.environ.get("GOOGLE_PAGESPEED_API_KEY")
    tech_only = "--tech-only" in args
    psi_only = "--psi-only" in args
    crawl_only = "--crawl-only" in args
    max_pages = 100

    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("http"):
            url = a
        elif a == "--competitor" and i + 1 < len(args):
            competitor = args[i + 1]
            i += 1
        elif a == "--locale" and i + 1 < len(args):
            pair = args[i + 1]
            if "=" in pair:
                lang, lurl = pair.split("=", 1)
                locale_urls[lang.strip()] = lurl.strip()
            i += 1
        elif a == "--key" and i + 1 < len(args):
            api_key = args[i + 1]
            i += 1
        elif a == "--pages" and i + 1 < len(args):
            try:
                max_pages = int(args[i + 1])
            except ValueError:
                pass
            i += 1
        i += 1

    return url, competitor, locale_urls, api_key, tech_only, psi_only, crawl_only, max_pages


def fmt(val):
    if val is None:
        return "N/A"
    if isinstance(val, bool):
        return "YES" if val else "NO"
    return str(val)


def print_psi_block(label: str, psi: dict):
    print(f"\n  [{label}]")
    if not psi.get("psi_ran"):
        print(f"    PSI did not run: {psi.get('psi_error', 'unknown error')}")
        return

    print(f"    Performance:      {fmt(psi.get('performance_score'))}")
    print(f"    Accessibility:    {fmt(psi.get('accessibility_score'))}")
    print(f"    SEO:              {fmt(psi.get('seo_score'))}")
    print(f"    Best Practices:   {fmt(psi.get('best_practices_score'))}")
    print(f"    LCP:              {fmt(psi.get('lcp'))}  (score: {fmt(psi.get('lcp_score'))})")
    print(f"    CLS:              {fmt(psi.get('cls'))}  (score: {fmt(psi.get('cls_score'))})")
    print(f"    INP:              {fmt(psi.get('inp'))}  (score: {fmt(psi.get('inp_score'))})")
    print(f"    FCP:              {fmt(psi.get('fcp'))}")
    print(f"    TBT:              {fmt(psi.get('tbt'))}")
    print(f"    Server resp time: {fmt(psi.get('server_response_time'))}")
    print(f"    Speed Index:      {fmt(psi.get('speed_index'))}")
    print(f"    CWV LCP:          {fmt(psi.get('cwv_lcp_category'))}")
    print(f"    CWV CLS:          {fmt(psi.get('cwv_cls_category'))}")
    print(f"    CWV INP:          {fmt(psi.get('cwv_inp_category'))}")
    print(f"    TTI:              {fmt(psi.get('time_to_interactive'))}  (score: {fmt(psi.get('time_to_interactive_score'))})")
    print(f"    TBT score:        {fmt(psi.get('total_blocking_time_score'))}")
    print(f"    Speed idx score:  {fmt(psi.get('speed_index_score'))}")
    print(f"    DOM size:         {fmt(psi.get('dom_size'))}")
    print(f"    3rd party block:  {fmt(psi.get('third_party_blocking_time'))}")
    print(f"    Meta description: {fmt(psi.get('has_meta_description'))}")
    print(f"    Canonical tag:    {fmt(psi.get('has_canonical'))}")
    print(f"    Hreflang audit:   {fmt(psi.get('hreflang_audit_pass'))}")
    print(f"    Robots.txt valid: {fmt(psi.get('robots_txt_valid'))}")
    print(f"    Is crawlable:     {fmt(psi.get('is_crawlable'))}")
    print(f"    Image alt score:  {fmt(psi.get('image_alt_score'))}")
    print(f"    Link text ok:     {fmt(psi.get('link_text_ok'))}")
    print(f"    Font size ok:     {fmt(psi.get('font_size_ok'))}")
    print(f"    Render blocking:  {fmt(psi.get('render_blocking_resources'))}  {fmt(psi.get('render_blocking_savings'))}")
    print(f"    Unused JS:        {fmt(psi.get('unused_javascript'))}  {fmt(psi.get('unused_javascript_savings'))}")
    print(f"    Unused CSS:       {fmt(psi.get('unused_css'))}  {fmt(psi.get('unused_css_savings'))}")
    print(f"    Unminified JS:    {fmt(psi.get('unminified_javascript'))}  {fmt(psi.get('unminified_javascript_savings'))}")
    print(f"    Unminified CSS:   {fmt(psi.get('unminified_css'))}  {fmt(psi.get('unminified_css_savings'))}")
    print(f"    Unoptimized img:  {fmt(psi.get('unoptimized_images'))}  {fmt(psi.get('unoptimized_images_savings'))}")
    print(f"    Next-gen images:  {fmt(psi.get('next_gen_images'))}  {fmt(psi.get('next_gen_images_savings'))}")
    print(f"    Offscreen images: {fmt(psi.get('offscreen_images'))}  {fmt(psi.get('offscreen_images_savings'))}")
    print(f"    Text compression: {fmt(psi.get('uses_text_compression'))}")
    print(f"    Cache efficient:  {fmt(psi.get('efficient_cache'))}  {fmt(psi.get('cache_savings'))}")


def print_crawl_section(result: dict):
    """Display crawl results. Works with both raw gather_site_crawl_facts output
    and the promoted fields in the full gather_pillar2_facts result dict."""
    def g(key, *fallbacks):
        for k in (key,) + fallbacks:
            v = result.get(k)
            if v is not None:
                return v
        return None

    print(f"\n-- Site crawl ({fmt(result.get('pages_crawled'))} pages) --")
    if not result.get("crawl_ran"):
        print(f"  Crawl did not run: {result.get('crawl_error', 'unknown')}")
        return
    print(f"Broken link occurrences: {fmt(g('broken_internal_links'))}")
    print(f"Broken unique URLs:   {fmt(g('broken_internal_urls'))}")
    print(f"HTTPS→HTTP links:     {fmt(g('https_to_http_links'))}")
    print(f"Redirect pages:       {fmt(g('redirect_pages'))}")
    print(f"Missing title:        {fmt(g('missing_title_pages', 'missing_title'))}")
    print(f"Short title (<30):    {fmt(g('short_title_pages', 'short_title'))}")
    print(f"Long title (>60):     {fmt(g('long_title_pages', 'long_title'))}")
    print(f"Duplicate titles:     {fmt(g('duplicate_title_pages', 'duplicate_titles'))}")
    print(f"Missing meta desc:    {fmt(g('missing_meta_descriptions'))}")
    print(f"Duplicate meta desc:  {fmt(g('duplicate_meta_pages', 'duplicate_meta_descriptions'))}")
    print(f"Missing H1:           {fmt(g('missing_h1_pages', 'missing_h1'))}")
    print(f"Multiple H1:          {fmt(g('multiple_h1_pages', 'multiple_h1'))}")
    print(f"H1 duplicates title:  {fmt(g('h1_duplicates_title_pages', 'h1_duplicates_title'))}")
    print(f"Missing canonical:    {fmt(g('missing_canonical_pages', 'missing_canonical'))}")
    print(f"No hreflang:          {fmt(g('pages_without_hreflang'))}")
    print(f"Hreflang no self-ref: {fmt(g('pages_hreflang_no_self'))}")
    print(f"Pages w/ missing alt: {fmt(g('images_missing_alt', 'pages_with_missing_alt'))}")
    print(f"Total imgs missing alt:{fmt(g('images_missing_alt_total'))}")
    print(f"Thin content (<300w): {fmt(g('thin_content_pages'))}")
    print(f"Avg word count:       {fmt(g('avg_word_count'))}")
    print(f"Avg text/HTML ratio:  {fmt(g('avg_text_to_html_ratio'))}")
    print(f"Empty anchor links:   {fmt(g('empty_anchor_links_total'))}")
    print(f"Max crawl depth:      {fmt(g('max_crawl_depth'))}")
    print(f"Avg crawl depth:      {fmt(g('avg_crawl_depth'))}")
    print(f"Pages deep (depth>3): {fmt(g('pages_deep_crawl'))}")
    print(f"Sitemap URLs:         {fmt(g('sitemap_urls_count'))}")
    print(f"Orphan pages:         {fmt(g('orphan_pages'))}")


def main():
    url, competitor, locale_urls, api_key, tech_only, psi_only, crawl_only, max_pages = parse_args()

    if not url:
        print("Usage: python test_website_health.py <url> [--competitor <url>] [--locale lang=url] [--key <api_key>]")
        sys.exit(1)

    from app.website_health import (
        gather_pagespeed_data,
        gather_homepage_technical_facts,
        gather_pillar2_facts,
    )

    print(f"\n{'='*60}")
    print(f"  Website Health Test: {url}")
    print(f"{'='*60}")
    if api_key:
        print(f"  API key: ...{api_key[-6:]}")
    else:
        print(f"  API key: none (rate-limited to ~400 req/day)")
    if locale_urls:
        print(f"  Locale URLs: {locale_urls}")
    if competitor:
        print(f"  Competitor: {competitor}")
    print()

    # -----------------------------------------------------------------------
    # Full gather_pillar2_facts run
    # -----------------------------------------------------------------------
    if not tech_only and not psi_only and not crawl_only:
        result = gather_pillar2_facts(
            url,
            locale_urls=locale_urls or None,
            semrush_data=None,
            api_key=api_key,
        )
    elif tech_only or psi_only or crawl_only:
        result = None

    # -----------------------------------------------------------------------
    # Print results
    # -----------------------------------------------------------------------
    if result is not None:
        print(f"\n{'='*60}")
        print("  PILLAR 2 RESULTS")
        print(f"{'='*60}")
        print(f"PSI ran:              {fmt(result.get('psi_ran'))}")
        print(f"Pages tested:         {fmt(result.get('pages_tested'))}")
        print(f"SEMrush available:    {fmt(result.get('semrush_available'))}")
        print(f"\nPerformance (mobile): {fmt(result.get('performance_score_mobile'))}")
        print(f"Performance (desktop):{fmt(result.get('performance_score_desktop'))}")
        print(f"SEO (mobile):         {fmt(result.get('seo_score_mobile'))}")
        print(f"Accessibility:        {fmt(result.get('accessibility_score_mobile'))}")
        print(f"LCP (mobile):         {fmt(result.get('lcp_mobile'))}")
        print(f"CLS (mobile):         {fmt(result.get('cls_mobile'))}")
        print(f"INP (mobile):         {fmt(result.get('inp_mobile'))}")
        print(f"LCP (desktop):        {fmt(result.get('lcp_desktop'))}")
        print(f"CWV LCP category:     {fmt(result.get('cwv_lcp_category'))}")
        print(f"CWV CLS category:     {fmt(result.get('cwv_cls_category'))}")
        print(f"CWV INP category:     {fmt(result.get('cwv_inp_category'))}")

        print(f"\n-- Technical checks --")
        print(f"robots.txt:           {fmt(result.get('has_robots_txt'))}")
        print(f"sitemap.xml:          {fmt(result.get('has_sitemap_xml'))}")
        print(f"llms.txt:             {fmt(result.get('has_llms_txt'))}")
        print(f"HSTS:                 {fmt(result.get('hsts_present'))}")
        print(f"HTTPS redirect:       {fmt(result.get('https_redirect'))}")
        print(f"H1 count:             {fmt(result.get('h1_count'))}")
        print(f"H1 texts:             {result.get('h1_texts', [])}")
        print(f"Schema.org types:     {result.get('schema_types', [])}")

        print(f"\n-- SEO sub-audits (from mobile PSI) --")
        print(f"Meta description:     {fmt(result.get('has_meta_description'))}")
        print(f"Canonical tag:        {fmt(result.get('has_canonical'))}")
        print(f"Hreflang audit:       {fmt(result.get('hreflang_audit_pass'))}")
        print(f"Robots.txt valid:     {fmt(result.get('robots_txt_valid'))}")
        print(f"Is crawlable:         {fmt(result.get('is_crawlable'))}")
        print(f"Image alt score:      {fmt(result.get('image_alt_score'))}")
        print(f"Render blocking res:  {fmt(result.get('render_blocking_resources'))}")
        print(f"Unused JavaScript:    {fmt(result.get('unused_javascript'))}")
        print(f"Unused CSS:           {fmt(result.get('unused_css'))}")
        print(f"Text compression:     {fmt(result.get('uses_text_compression'))}")

        if result.get("locale_psi_results"):
            print(f"\n-- Locale page PSI ({len(result['locale_psi_results'])} pages) --")
            print(f"Mobile perf range:    {fmt(result.get('locale_performance_min'))} - {fmt(result.get('locale_performance_max'))} (avg {fmt(result.get('locale_performance_avg'))})")
            print(f"Desktop perf range:   {fmt(result.get('locale_desktop_performance_min'))} - {fmt(result.get('locale_desktop_performance_max'))} (avg {fmt(result.get('locale_desktop_performance_avg'))})")
            for lp in result["locale_psi_results"]:
                mobile_status = "OK" if lp.get("psi_ran") else f"FAILED ({lp.get('psi_error', '?')})"
                desktop_status = "OK" if lp.get("psi_ran_desktop") else f"FAILED ({lp.get('psi_error_desktop', '?')})"
                print(f"  [{lp['lang']}] {lp['url']}")
                print(f"       mobile:  perf={fmt(lp.get('performance_score'))}  seo={fmt(lp.get('seo_score'))}  lcp={fmt(lp.get('lcp'))}  {mobile_status}")
                print(f"       desktop: perf={fmt(lp.get('performance_score_desktop'))}  lcp={fmt(lp.get('lcp_desktop'))}  {desktop_status}")

        # Site crawl summary
        print_crawl_section(result)

        # Detailed per-strategy PSI blocks
        print(f"\n-- Homepage PSI detail --")
        print_psi_block("mobile", result.get("homepage_mobile", {}))
        print_psi_block("desktop", result.get("homepage_desktop", {}))

    # -----------------------------------------------------------------------
    # tech-only mode
    # -----------------------------------------------------------------------
    elif tech_only:
        print(f"\nRunning technical checks only for {url} ...")
        tech = gather_homepage_technical_facts(url)
        print(f"\n{'='*60}")
        print("  TECHNICAL CHECKS")
        print(f"{'='*60}")
        print(f"Checker ran:    {fmt(tech.get('checker_ran'))}")
        if tech.get("checker_error"):
            print(f"Error:          {tech['checker_error']}")
        print(f"robots.txt:     {fmt(tech.get('has_robots_txt'))}")
        print(f"sitemap.xml:    {fmt(tech.get('has_sitemap_xml'))}")
        print(f"llms.txt:       {fmt(tech.get('has_llms_txt'))}")
        print(f"HSTS:           {fmt(tech.get('hsts_present'))}")
        print(f"HTTPS redirect: {fmt(tech.get('https_redirect'))}")
        print(f"H1 count:       {fmt(tech.get('h1_count'))}")
        print(f"H1 texts:       {tech.get('h1_texts', [])}")
        print(f"Schema types:   {tech.get('schema_types', [])}")

    # -----------------------------------------------------------------------
    # psi-only mode
    # -----------------------------------------------------------------------
    elif psi_only:
        print(f"\nRunning PSI only for {url} ...")
        mobile = gather_pagespeed_data(url, strategy="mobile", api_key=api_key)
        desktop = gather_pagespeed_data(url, strategy="desktop", api_key=api_key)
        print(f"\n{'='*60}")
        print("  PSI RESULTS")
        print(f"{'='*60}")
        print_psi_block("mobile", mobile)
        print_psi_block("desktop", desktop)

    # -----------------------------------------------------------------------
    # crawl-only mode
    # -----------------------------------------------------------------------
    elif crawl_only:
        print(f"\nRunning site crawl only for {url} (max {max_pages} pages) ...")
        try:
            from app.website_health import gather_site_crawl_facts
            crawl = gather_site_crawl_facts(url, max_pages=max_pages)
        except ImportError:
            print("  gather_site_crawl_facts not available — use gather_pillar2_facts instead (no --crawl-only flag)")
            crawl = {}
        print(f"\n{'='*60}")
        print("  SITE CRAWL RESULTS")
        print(f"{'='*60}")
        print_crawl_section(crawl)

    # -----------------------------------------------------------------------
    # Competitor benchmark
    # -----------------------------------------------------------------------
    if competitor:
        print(f"\n{'='*60}")
        print(f"  COMPETITOR: {competitor}")
        print(f"{'='*60}")
        comp_mobile = gather_pagespeed_data(competitor, strategy="mobile", api_key=api_key)
        comp_desktop = gather_pagespeed_data(competitor, strategy="desktop", api_key=api_key)
        print_psi_block("mobile", comp_mobile)
        print_psi_block("desktop", comp_desktop)

    # -----------------------------------------------------------------------
    # Full JSON dump
    # -----------------------------------------------------------------------
    if result is not None:
        print(f"\n--- Full JSON (gather_pillar2_facts) ---")
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
