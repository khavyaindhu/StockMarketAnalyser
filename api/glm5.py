import os
import ollama

MODEL = os.getenv("GLM5_MODEL", "glm-5:cloud")


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


def _build_chat_prompt(user_question: str, context: str) -> str:
    return f"""You are a financial assistant for an Indian stock market investor.

Portfolio context:
{context}

User question: {user_question}

Answer concisely and specifically. Focus on Indian market dynamics."""


def analyze_stock(stock_name: str, ticker: str, news: list, sentiment_data: list) -> str:
    """Returns AI analysis for a single stock using news + sentiment data."""
    prompt = _build_portfolio_prompt(stock_name, ticker, news, sentiment_data)
    try:
        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        return response["message"]["content"]
    except Exception as e:
        return f"Error connecting to Ollama: {e}\n\nMake sure Ollama is running (`ollama serve`) and you are signed in (`ollama signin`) for cloud models."


def analyze_theme(theme_name: str, impact_note: str, news: list, affected_stocks: list) -> str:
    """Returns AI analysis for a macro theme."""
    prompt = _build_theme_prompt(theme_name, impact_note, news, affected_stocks)
    try:
        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        return response["message"]["content"]
    except Exception as e:
        return f"Error connecting to Ollama: {e}"


def stream_chat(messages: list):
    """Yields content chunks for streaming chat responses."""
    try:
        stream = ollama.chat(
            model=MODEL,
            messages=messages,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.get("message", {}).get("content", "")
            if delta:
                yield delta
    except Exception as e:
        yield f"Error connecting to Ollama: {e}\n\nMake sure Ollama is running (`ollama serve`) and you are signed in (`ollama signin`)."
