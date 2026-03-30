"""
Quick test for the SEMrush PDF parser.
Run from the backend/ directory:
    power/bin/python3 test_semrush_parser.py path/to/report.pdf
"""
import sys
import json
from app.semrush_parser import parse_semrush_pdf

pdf_path = sys.argv[1] if len(sys.argv) > 1 else \
    "../Semrush-Full_Site_Audit_Report-www_bigpanda_io-6th_Feb_2026 (1).pdf"

result = parse_semrush_pdf(pdf_path)

print(json.dumps(result, indent=2))

missing = [k for k, v in result.items() if v is None]
found   = [k for k, v in result.items() if v is not None]

print(f"\n--- Summary ---")
print(f"Fields extracted:  {len(found)}")
print(f"Fields missing:    {len(missing)}")
if missing:
    print(f"Missing fields: {missing}")
