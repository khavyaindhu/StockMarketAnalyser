# Personal portfolio — add or remove stocks here
# ticker: BSE symbol used by AlphaVantage
# keywords: search terms used by Mediastack news fetch
# sector: used for theme grouping

PORTFOLIO = {
    "Wipro": {
        "ticker": "WIPRO.BSE",
        "keywords": ["Wipro", "Wipro IT", "Wipro quarterly"],
        "sector": "IT",
    },
    "Manappuram Finance": {
        "ticker": "MANAPPURAM.BSE",
        "keywords": ["Manappuram Finance", "Manappuram gold loan", "NBFC gold loan India"],
        "sector": "Finance",
    },
    # TMCV and TMPV are Tata Motors CV/PV divisions — not separately listed on BSE yet.
    # Both are mapped to TATAMOTORS.BSE. Update tickers if/when they list separately.
    "Tata Motors (CV)": {
        "ticker": "TATAMOTORS.BSE",
        "keywords": ["Tata Motors commercial vehicle", "TMCV", "Tata CV sales"],
        "sector": "Auto",
    },
    "Tata Motors (PV)": {
        "ticker": "TATAMOTORS.BSE",
        "keywords": ["Tata Motors passenger vehicle", "TMPV", "Tata EV", "Tata Nexon"],
        "sector": "Auto",
    },
}

# Macro theme definitions — news keywords + which portfolio stocks are affected
THEMES = {
    "Oil & Energy": {
        "keywords": ["crude oil price", "OPEC", "Iran war oil", "oil supply"],
        "affected_sectors": ["Auto", "Finance"],
        "impact_note": "Rising oil raises input costs for Auto; tightens consumer spending affecting NBFCs.",
    },
    "IT Sector / AI": {
        "keywords": ["Indian IT slowdown", "AI automation jobs", "IT layoffs India", "US tech spending"],
        "affected_sectors": ["IT"],
        "impact_note": "AI disruption and US tech budget cuts directly affect Indian IT exports.",
    },
    "Gold Prices": {
        "keywords": ["gold price India", "gold rate rise", "gold demand India"],
        "affected_sectors": ["Finance"],
        "impact_note": "Rising gold prices boost collateral value for gold loan NBFCs like Manappuram.",
    },
    "RBI / Interest Rates": {
        "keywords": ["RBI rate hike", "repo rate India", "RBI monetary policy"],
        "affected_sectors": ["Finance", "Auto"],
        "impact_note": "Rate hikes raise borrowing costs, hurting NBFCs and dampening auto sales.",
    },
    "EV / Auto Policy": {
        "keywords": ["EV India policy", "electric vehicle India", "PLI auto scheme", "Tata Motors EV"],
        "affected_sectors": ["Auto"],
        "impact_note": "Government EV push and PLI incentives directly benefit Tata Motors.",
    },
}
