import os
from openai import OpenAI

try:
    from app.log_ctx import plog
except ImportError:
    from log_ctx import plog

try:
    from app.audit import _parse_json
except ImportError:
    from audit import _parse_json

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

VALID_INDUSTRIES = {
    "Retail & Ecommerce",
    "Travel & Hospitality",
    "Media & Entertainment",
    "Public Sector",
    "Life Sciences",
    "Banking & Finance",
    "Legal",
    "Manufacturing",
    "Technology & Software",
    "Professional Services",
    "Defense & Aerospace",
}

VALID_SIZES = {"SMB", "Mid-Market", "Enterprise"}
VALID_MODELS = {"B2C", "B2B", "Mixed"}

_CLASSIFY_PROMPT = """
You are classifying a company to determine its language localization requirements.
Research {company_name} ({url}) online and return a JSON object with these exact fields:

{{
  "industry": one of exactly: "Retail & Ecommerce" | "Travel & Hospitality" | "Media & Entertainment" | "Public Sector" | "Life Sciences" | "Banking & Finance" | "Legal" | "Manufacturing" | "Technology & Software" | "Professional Services" | "Defense & Aerospace",
  "company_size": one of exactly: "SMB" | "Mid-Market" | "Enterprise",
  "business_model": one of exactly: "B2C" | "B2B" | "Mixed",
  "confidence_notes": "1-2 sentences explaining your classification"
}}

Classification rules:
- company_size: SMB = under 100 employees or under $50M revenue. Mid-Market = 100-999 employees or $50M-$1B revenue. Enterprise = 1000+ employees or over $1B revenue.
- business_model: B2C if end consumers buy directly. B2B if selling to businesses. Mixed if both.
- industry definitions:
  - Retail & Ecommerce: sells physical or digital products directly via an online store or retail channels.
  - Travel & Hospitality: airlines, hotels, tour operators, booking platforms, restaurants, leisure.
  - Media & Entertainment: publishers, streaming, gaming, news, sports, advertising.
  - Public Sector: government agencies, public institutions, NGOs, educational bodies.
  - Life Sciences: pharma, biotech, medical devices, clinical research, healthcare providers.
  - Banking & Finance: banks, insurance, fintech, investment, payments, wealth management.
  - Legal: law firms, legal services, compliance, regulatory advisory.
  - Manufacturing: industrial production, hardware, physical goods manufacturing, supply chain.
  - Technology & Software: primary value is a software product or tech platform (SaaS, cloud, apps, APIs). Use this ONLY if the company's core offering is software itself.
  - Professional Services: companies selling expertise or human-delivered services — consulting, translation, localization, staffing, accounting, marketing agencies, audit firms. If a company uses technology to deliver services but the core offering is the service, choose this over Technology & Software.
  - Defense & Aerospace: defense contractors, aerospace manufacturers, security systems.

Return only valid JSON, no markdown.
"""


def classify_company(url: str, company_name: str) -> dict:
    """
    Classify a company's industry, size, business model, and target markets.
    Returns a dict with those fields, or a fallback dict with None values if classification fails.
    """
    prompt = _CLASSIFY_PROMPT.format(company_name=company_name, url=url)

    try:
        resp = client.responses.create(
            model="gpt-5.4-nano",
            tools=[{"type": "web_search"}],
            input=prompt.strip(),
        )
        plog(f"[classify] tokens: input={getattr(resp.usage, 'input_tokens', '?')} output={getattr(resp.usage, 'output_tokens', '?')}")

        data = _parse_json(resp.output_text, label="classify")
        if not isinstance(data, dict):
            raise ValueError("Classification response is not a dict")

        # Validate and fallback to None for invalid values
        industry = data.get("industry")
        if industry not in VALID_INDUSTRIES:
            plog(f"[classify] Invalid industry '{industry}', setting to None")
            industry = None

        company_size = data.get("company_size")
        if company_size not in VALID_SIZES:
            plog(f"[classify] Invalid company_size '{company_size}', setting to None")
            company_size = None

        business_model = data.get("business_model")
        if business_model not in VALID_MODELS:
            plog(f"[classify] Invalid business_model '{business_model}', setting to None")
            business_model = None

        return {
            "industry": industry,
            "company_size": company_size,
            "business_model": business_model,
            "confidence_notes": data.get("confidence_notes", ""),
        }

    except Exception as e:
        plog(f"[classify] ERROR: {e}")
        return {
            "industry": None,
            "company_size": None,
            "business_model": None,
            "confidence_notes": "",
        }
