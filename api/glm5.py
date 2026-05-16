import os
import json
import requests

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "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")
# Free models on OpenRouter — swap this string to try different models:
#   "google/gemini-2.0-flash-exp:free"
#   "deepseek/deepseek-r1:free"
#   "mistralai/mistral-7b-instruct:free"
#   "meta-llama/llama-3.3-70b-instruct:free"  ← default (strong, free)
MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/StockMarketAnalyser",
        "X-Title": "Stock Market Analyser",
    }


def _chat(messages: list) -> str:
    payload = {"model": MODEL, "messages": messages, "temperature": 0.7}
    try:
        r = requests.post(OPENROUTER_URL, json=payload, headers=_headers(), timeout=60)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e:
        return f"Error calling OpenRouter API: {e}"


def _build_portfolio_prompt(stock_name: str, ticker: str, news: list, sentiment_data: list) -> str:
    news_block = "\n".join(
        f"- {a['title']} ({a['source']}, {a.get('published_at', '')[:10]})"
        for a in news[:6]
    ) or "No recent news available."

    if sentiment_data:
        scores = []
        headlines = []
        for a in sentiment_data[:5]:
            try:
                scores.append(float(a.get("Score", 0)))
                headlines.append(f"  - {a.get('Headline', '')} [Score: {a.get('Score', 'N/A')}, {a.get('Sentiment', '')}]")
            except (ValueError, TypeError):
                pass
        avg_score = sum(scores) / len(scores) if scores else 0
        sentiment_block = f"Average sentiment score: {avg_score:.3f}\nTop headlines:\n" + "\n".join(headlines)
    else:
        sentiment_block = "No sentiment data available."

    return f"""You are a financial analyst assistant specializing in Indian stock markets.

Analyze the following data for {stock_name} ({ticker}) and provide:
1. A brief summary of the current market sentiment
2. Key risks and opportunities based on the news
3. A short-term outlook (1-2 weeks)
4. One actionable insight for an investor

--- RECENT NEWS ---
{news_block}

--- SENTIMENT DATA (AlphaVantage) ---
{sentiment_block}

Be concise, factual, and specific to Indian market context. Avoid generic advice."""


def _build_theme_prompt(theme_name: str, impact_note: str, news: list, affected_stocks: list) -> str:
    news_block = "\n".join(
        f"- {a['title']} ({a['source']}, {a.get('published_at', '')[:10]})"
        for a in news[:8]
    ) or "No recent news available."

    stocks_block = ", ".join(affected_stocks) if affected_stocks else "None in portfolio."

    return f"""You are a macro analyst specializing in Indian equity markets.

Macro theme: {theme_name}
Impact logic: {impact_note}
Affected portfolio stocks: {stocks_block}

Recent news related to this theme:
{news_block}

Provide:
1. How this macro theme is currently playing out in India
2. Specific impact on the affected stocks listed
3. Whether the news sentiment suggests this trend is strengthening or weakening
4. One portfolio action to consider

Be specific, concise, and grounded in the news provided."""


def analyze_stock(stock_name: str, ticker: str, news: list, sentiment_data: list) -> str:
    prompt = _build_portfolio_prompt(stock_name, ticker, news, sentiment_data)
    return _chat([{"role": "user", "content": prompt}])


def analyze_theme(theme_name: str, impact_note: str, news: list, affected_stocks: list) -> str:
    prompt = _build_theme_prompt(theme_name, impact_note, news, affected_stocks)
    return _chat([{"role": "user", "content": prompt}])


def stream_chat(messages: list):
    payload = {"model": MODEL, "messages": messages, "temperature": 0.7, "stream": True}
    try:
        with requests.post(OPENROUTER_URL, json=payload, headers=_headers(), stream=True, timeout=60) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield delta
    except requests.exceptions.RequestException as e:
        yield f"Error calling OpenRouter API: {e}"
