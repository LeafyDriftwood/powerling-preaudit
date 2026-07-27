import json
from pathlib import Path

_matrix = json.loads((Path(__file__).parent / "rl_matrix.json").read_text())

_MARKET_LANGUAGES: dict[str, list[str]] = _matrix["market_languages"]
_REGULATORY_RULES: list[dict] = _matrix["regulatory_rules"]

_ENGLISH_TOLERANT_MARKETS: set[str] = {"NL", "SE", "NO", "DK", "FI"}

_VALID_EVIDENCE: set[str] = {"commercial_page", "commercial_presence", "country_selector", "traffic"}

# map of variant languages to their base ISO code 
_LANG_ALIASES: dict[str, str] = {
    "nb": "no",  # Norwegian Bokmal -> Norwegian
    "nn": "no",  # Norwegian Nynorsk -> Norwegian
}


_LANG_NAMES: dict[str, str] = {
    "af": "Afrikaans", "ar": "Arabic", "az": "Azerbaijani", "be": "Belarusian",
    "bg": "Bulgarian", "bn": "Bengali", "bs": "Bosnian", "ca": "Catalan",
    "cs": "Czech", "cy": "Welsh", "da": "Danish", "de": "German",
    "el": "Greek", "en": "English", "es": "Spanish", "et": "Estonian",
    "eu": "Basque", "fa": "Persian", "fi": "Finnish", "fr": "French",
    "ga": "Irish", "gl": "Galician", "gu": "Gujarati", "he": "Hebrew",
    "hi": "Hindi", "hr": "Croatian", "ht": "Haitian Creole", "hu": "Hungarian",
    "hy": "Armenian", "id": "Indonesian", "is": "Icelandic", "it": "Italian",
    "ja": "Japanese", "ka": "Georgian", "kk": "Kazakh", "km": "Khmer",
    "kn": "Kannada", "ko": "Korean", "lt": "Lithuanian", "lv": "Latvian",
    "mk": "Macedonian", "ml": "Malayalam", "mn": "Mongolian", "mr": "Marathi",
    "ms": "Malay", "my": "Burmese", "ne": "Nepali", "nl": "Dutch",
    "no": "Norwegian", "pa": "Punjabi", "pl": "Polish", "pt": "Portuguese",
    "ro": "Romanian", "ru": "Russian", "si": "Sinhala", "sk": "Slovak",
    "sl": "Slovenian", "sq": "Albanian", "sr": "Serbian", "sv": "Swedish",
    "sw": "Swahili", "ta": "Tamil", "te": "Telugu", "th": "Thai",
    "tl": "Filipino", "tr": "Turkish", "uk": "Ukrainian", "ur": "Urdu",
    "uz": "Uzbek", "vi": "Vietnamese", "zh": "Chinese",
}

_COUNTRY_NAMES: dict[str, str] = {
    "AE": "UAE", "AR": "Argentina", "AT": "Austria", "AU": "Australia",
    "BE": "Belgium", "BG": "Bulgaria", "BR": "Brazil", "CA": "Canada",
    "CH": "Switzerland", "CL": "Chile", "CN": "China", "CO": "Colombia",
    "CZ": "Czechia", "DE": "Germany", "DK": "Denmark", "DZ": "Algeria",
    "EE": "Estonia", "EG": "Egypt", "ES": "Spain", "FI": "Finland",
    "FR": "France", "GB": "UK", "GR": "Greece", "HK": "Hong Kong",
    "HR": "Croatia", "HU": "Hungary", "ID": "Indonesia", "IE": "Ireland",
    "IL": "Israel", "IN": "India", "IT": "Italy", "JP": "Japan",
    "KE": "Kenya", "KR": "South Korea", "LT": "Lithuania", "LU": "Luxembourg",
    "LV": "Latvia", "MA": "Morocco", "MX": "Mexico", "MY": "Malaysia",
    "NG": "Nigeria", "NL": "Netherlands", "NO": "Norway", "NZ": "New Zealand",
    "PE": "Peru", "PH": "Philippines", "PK": "Pakistan", "PL": "Poland",
    "PT": "Portugal", "RO": "Romania", "RU": "Russia", "SA": "Saudi Arabia",
    "SE": "Sweden", "SG": "Singapore", "SI": "Slovenia", "SK": "Slovakia",
    "TH": "Thailand", "TN": "Tunisia", "TR": "Turkey", "TW": "Taiwan",
    "UA": "Ukraine", "US": "United States", "VN": "Vietnam", "ZA": "South Africa",
}

_EVIDENCE_LABELS: dict[str, str] = {
    "commercial_page": "commercial domain or regional site",
    "commercial_presence": "confirmed commercial activity",
    "country_selector": "country selector entry",
    "traffic": "significant web traffic",
}


def _commercial_expectation(is_b2c: bool, country: str) -> str:
    """Returns 'strong', 'medium', or 'none' based on business type and whether country is english tolerant."""
    et_market = country in _ENGLISH_TOLERANT_MARKETS
    if is_b2c:
        return "medium" if et_market else "strong"
    return "none" if et_market else "medium"


def _build_reason(lang: str, country: str, evidence_type: str, is_b2c: bool) -> str:
    lang_name = _LANG_NAMES.get(lang.lower(), lang.upper())
    country_name = _COUNTRY_NAMES.get(country, country)
    evidence_label = _EVIDENCE_LABELS.get(evidence_type, "presence")
    bm_label = "B2C" if is_b2c else "B2B"
    return f"{country_name} {evidence_label} detected: {lang_name} expected for {bm_label} coverage"


def _regulatory_gaps(
    strong_medium_markets: list[dict],
    avail: set[str],
    is_b2c: bool,
) -> list[dict]:
    """
    Loads rules from rl_matrix.json regulatory_rules.
    """
    if not is_b2c:
        return []

    gaps: list[dict] = []
    by_country = {m["country"].upper(): m for m in strong_medium_markets}

    for rule in _REGULATORY_RULES:
        if rule.get("trigger_business_model") != "B2C":
            continue
        country = rule["trigger_country"]
        if country not in by_country:
            continue
        for lang in rule["langs"]:
            if lang not in avail:
                lang_name = _LANG_NAMES.get(lang, lang.upper())
                reason = rule["reason"].format(lang_name=lang_name)
                gaps.append({
                    "language": lang.upper(),
                    "market": country,
                    "strength": "strong",
                    "reason": reason,
                    "regulatory": True,
                })

    return gaps


def compute_language_gaps(
    observed_markets: list[dict] | None,
    available_languages: list[str] | None,
    business_model: str | None,
    vertical: str | None,
) -> dict:
    """
    Returns gaps in language coverage based on observed_markets, available_languages, and business_model.
    Looks something like this:
      {
        "state": "aligned" | "potential_gaps" | "needs_confirmation",
        "gaps": [
          {
            "language": "FR",
            "market": "FR",
            "strength": "strong" | "medium",
            "reason": "...",
            "regulatory": bool
          }
        ]
      }
    """
    is_b2c = (business_model or "").upper() == "B2C"
    avail = {_LANG_ALIASES.get(lang.lower(), lang.lower()) for lang in (available_languages or [])}

    _ = vertical  # just keeping it in case we want to use it for future logic

    observed: dict[str, dict] = {}
    for m in (observed_markets or []):
        code = m.get("country", "").upper()
        if code and code in _MARKET_LANGUAGES:
            observed[code] = {**m, "country": code}

    strong_medium = [m for m in observed.values() if m.get("evidence_type") in _VALID_EVIDENCE]

    if not strong_medium:
        # No solid evidence of which markets the company serves
        return {"state": "needs_confirmation", "gaps": []}

    gaps: list[dict] = []
    seen: set[tuple[str, str]] = set()  # (language, country)

    # commercial gaps: missing language for an observed market
    for market_entry in strong_medium:
        country = market_entry["country"]
        evidence_type = market_entry.get("evidence_type", "")

        for lang in _MARKET_LANGUAGES.get(country, []):
            if lang.lower() in avail:
                continue
            strength = _commercial_expectation(is_b2c, country)
            if strength == "none":
                continue
            key = (lang.upper(), country)
            if key in seen:
                continue
            seen.add(key)
            note = (market_entry.get("note") or "").strip()
            gaps.append({
                "language": lang.upper(),
                "market": country,
                "strength": strength,
                "reason": note or _build_reason(lang, country, evidence_type, is_b2c),
                "regulatory": False,
            })

    # regulatory gaps override commercial gaps for the same language+market pair, more severe
    for rg in _regulatory_gaps(strong_medium, avail, is_b2c):
        gaps = [g for g in gaps if (g["language"], g["market"]) != (rg["language"], rg["market"])]
        gaps.append(rg)

    # Sort by strong first, then alphabetically by market then language. Cap at 10.
    gaps.sort(key=lambda g: (0 if g["strength"] == "strong" else 1, g["market"], g["language"]))
    gaps = gaps[:10]

    return {"state": "potential_gaps" if gaps else "aligned", "gaps": gaps}
