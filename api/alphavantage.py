import os
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "1IIESJ7MS31GAH0O")


def get_quote(ticker: str) -> dict:
    """Returns current price and % change for a BSE ticker."""
    api_key = ALPHAVANTAGE_API_KEY
    if not api_key:
        return {"error": "AlphaVantage API key not found."}

    try:
        r = requests.get(
            "https://www.alphavantage.co/query",
            params={"function": "GLOBAL_QUOTE", "symbol": ticker, "apikey": api_key},
            timeout=10,
        )
        r.raise_for_status()
        quote = r.json().get("Global Quote", {})
        if not quote:
            return {"error": "No data (rate-limited or invalid ticker)."}
        return {
            "price": quote.get("05. price", "N/A"),
            "change": quote.get("09. change", "N/A"),
            "change_percent": quote.get("10. change percent", "N/A"),
        }
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}


def get_news_sentiment(ticker: str):
    """
    Fetches the latest news and sentiment for a given ticker from AlphaVantage.
    """
    api_key = ALPHAVANTAGE_API_KEY
    if not api_key:
        raise ValueError("AlphaVantage API key not found. Please check your .env file.")

    url = f'https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={ticker}&apikey={api_key}'
    
    try:
        r = requests.get(url)
        r.raise_for_status()
        data = r.json()
        
        # Check for API rate limits or errors
        if "Information" in data:
            return {"error": data["Information"]}
        if "Error Message" in data:
            return {"error": data["Error Message"]}
            
        results = []
        if 'feed' in data:
            for article in data['feed']:
                headline = article.get('title', 'No Title')
                sentiment = article.get('overall_sentiment_label', 'Neutral')
                score = article.get('overall_sentiment_score', '0')
                url_link = article.get('url', '#')
                source = article.get('source', 'Unknown Source')
                time_published = article.get('time_published', '')
                
                results.append({
                    "Headline": headline,
                    "Sentiment": sentiment,
                    "Score": score,
                    "Source": source,
                    "Published": time_published,
                    "URL": url_link
                })
        return {"data": results}
        
    except requests.exceptions.RequestException as e:
        return {"error": f"Failed to fetch data: {str(e)}"}
