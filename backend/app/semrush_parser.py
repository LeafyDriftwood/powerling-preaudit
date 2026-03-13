import re
import pdfplumber


def _clean(text: str) -> str:
    """Strip null bytes and normalize whitespace."""
    return text.replace('\x00', ' ').replace('\xa0', ' ')


def _extract_int(pattern: str, text: str, flags: int = re.IGNORECASE):
    m = re.search(pattern, text, flags)
    if m:
        return int(m.group(1).replace(',', ''))
    return None


def parse_semrush_pdf(pdf_path: str):
    """
    Parse a SEMrush Full Site Audit PDF export.

    Returns a dict of structured Pillar 2 metrics.
    Missing fields are None if not found 
    """
    with pdfplumber.open(pdf_path) as pdf:
        pages = [_clean(p.extract_text() or '') for p in pdf.pages[:20]]
        # "Missing h1" appears only as a section page header  and not in first pages
        section_headers = '\n'.join(
            _clean((p.extract_text() or '').split('\n')[2] if len((p.extract_text() or '').split('\n')) > 2 else '')
            for p in pdf.pages
        )

    summary = pages[1]     
    all_text = '\n'.join(pages)

    result = {}

    # Summary page
    result['pages_crawled'] = _extract_int(r'Crawled Pages[:\s]+(\d[\d,]*)', summary)
    result['site_health_score'] = _extract_int(r'(\d+)\s*\n%\s*Healthy', summary)

    # Page breakdown
    m = re.search(
        r'%\s*Healthy\s+(\d[\d,]*)\s+Broken\s+(\d[\d,]*)\s+Have issues\s+(\d[\d,]*)'
        r'\s+Redirected\s+(\d[\d,]*)\s+Blocked\s+(\d[\d,]*)',
        summary, re.IGNORECASE,
    )
    if m:
        result['healthy_pages']     = int(m.group(1).replace(',', ''))
        result['broken_pages']      = int(m.group(2).replace(',', ''))
        result['pages_with_issues'] = int(m.group(3).replace(',', ''))
        result['redirected_pages']  = int(m.group(4).replace(',', ''))
        result['blocked_pages']     = int(m.group(5).replace(',', ''))

    # Error warnings
    m = re.search(
        r'Errors\s+Warnings\s+Notices\s*\n(\d[\d,]*)\s+(\d[\d,]*)\s+(\d[\d,]*)',
        summary,
    )
    if m:
        result['errors_total']   = int(m.group(1).replace(',', ''))
        result['warnings_total'] = int(m.group(2).replace(',', ''))
        result['notices_total']  = int(m.group(3).replace(',', ''))

    # Counts for each issue

    # Errors
    result['broken_internal_links']       = _extract_int(r'(\d[\d,]*)\s+internal links? are broken', all_text)
    result['broken_external_links']       = _extract_int(r'(\d[\d,]*)\s+external links? are broken', all_text)
    result['pages_4xx']                   = _extract_int(r'(\d[\d,]*)\s+pages? returned 4[Xx][Xx] status', all_text)
    result['pages_5xx']                   = _extract_int(r'(\d[\d,]*)\s+pages? returned 5[Xx][Xx] status', all_text)
    result['duplicate_content_pages']     = _extract_int(r'(\d[\d,]*)\s+pages? have duplicate content issues', all_text)
    result['duplicate_title_pages']       = _extract_int(r'(\d[\d,]*)\s+issues? with duplicate title tags', all_text)
    result['pages_slow_load']             = _extract_int(r'(\d[\d,]*)\s+pages? have slow load speed', all_text)

    # Warnings
    result['missing_meta_descriptions']   = _extract_int(r"(\d[\d,]*)\s+pages? don'?t have meta descriptions", all_text)
    result['duplicate_meta_descriptions'] = _extract_int(r'(\d[\d,]*)\s+pages? have duplicate meta descriptions', all_text)
    result['images_missing_alt']          = _extract_int(r"(\d[\d,]*)\s+images? don'?t have alt attributes", all_text)
    result['multiple_h1_pages']           = _extract_int(r'(\d[\d,]*)\s+pages? have more than one H1 tag', all_text)
    result['unminified_js_css']           = _extract_int(r'(\d[\d,]*)\s+issues? with unminified JavaScript and CSS', all_text)
    result['temporary_redirects']         = _extract_int(r'(\d[\d,]*)\s+URLs? with a temporary redirect', all_text)
    result['low_word_count_pages']        = _extract_int(r'(\d[\d,]*)\s+pages? have a low word count', all_text)
    result['low_text_html_ratio_pages']   = _extract_int(r'(\d[\d,]*)\s+pages? have low text-HTML ratio', all_text)

    # Notices
    result['non_descriptive_anchors']     = _extract_int(r'(\d[\d,]*)\s+links? have non-descriptive anchor text', all_text)
    result['pages_deep_crawl']            = _extract_int(r'(\d[\d,]*)\s+pages? need more than 3 clicks to be reached', all_text)
    result['long_urls']                   = _extract_int(r'(\d[\d,]*)\s+page URLs? are longer than 200 characters', all_text)
    result['permanent_redirects']         = _extract_int(r'(\d[\d,]*)\s+URLs? with a permanent redirect', all_text)

    # SEO
    result['hreflang_value_issues']       = _extract_int(r'(\d[\d,]*)\s+issues? with hreflang values', all_text)
    result['hreflang_conflicts']          = _extract_int(r'(\d[\d,]*)\s+hreflang conflicts within page source', all_text)
    result['incorrect_hreflang_links']    = _extract_int(r'(\d[\d,]*)\s+issues? with incorrect hreflang links', all_text)
    result['pages_no_hreflang_lang']      = _extract_int(r'(\d[\d,]*)\s+pages? have no hreflang and lang attributes', all_text)
    result['hreflang_language_mismatch']  = _extract_int(r'(\d[\d,]*)\s+pages? have hreflang language mismatch', all_text)

    # Section headers with different format
    result['missing_h1']                  = _extract_int(r'Missing h1\s+(\d[\d,]*)', section_headers)

    return result
