import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)


def get_india_news(keywords: list[str], limit: int = 10) -> dict:
    api_key = os.getenv("MEDIASTACK_API_KEY")
    if not api_key:
        raise ValueError("Mediastack API key not found. Please check your .env file.")

    params = {
        "access_key": api_key,
        "keywords": ",".join(keywords),
        "countries": "in",
        "languages": "en",
        "limit": limit,
        "sort": "published_desc",
    }

    try:
        r = requests.get("http://api.mediastack.com/v1/news", params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        if "error" in data:
            return {"error": data["error"].get("message", "Unknown Mediastack error")}

        results = []
        for article in data.get("data", []):
            results.append({
                "title": article.get("title") or "No Title",
                "description": article.get("description") or "",
                "source": article.get("source") or "Unknown",
                "published_at": article.get("published_at") or "",
                "url": article.get("url") or "#",
            })
        return {"data": results}

    except requests.exceptions.RequestException as e:
        return {"error": f"Failed to fetch news: {str(e)}"}
