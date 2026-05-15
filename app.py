import streamlit as st
import pandas as pd
from api.alphavantage import get_news_sentiment
from api.nifty50 import NIFTY_50

st.set_page_config(page_title="Stock Market Analyser", page_icon="📈", layout="wide")

st.title("📈 Stock Market Analyser Dashboard")
st.markdown("Fetch real-time stock news and sentiment impact using AlphaVantage.")

# Sidebar for inputs
with st.sidebar:
    st.header("Search Parameters")
    mode = st.radio("Stock Mode", ["Custom Ticker", "Nifty 50"], horizontal=True)

    if mode == "Nifty 50":
        company = st.selectbox("Select Nifty 50 Stock", list(NIFTY_50.keys()))
        ticker = NIFTY_50[company]
        st.caption(f"AlphaVantage ticker: `{ticker}`")
    else:
        ticker = st.text_input("Enter Stock Ticker (e.g., AAPL, TSLA, MSFT)", value="AAPL")

    fetch_button = st.button("Fetch News Sentiment")

if fetch_button:
    if ticker:
        with st.spinner(f"Fetching news for {ticker.upper()}..."):
            response = get_news_sentiment(ticker.upper())
            
            if "error" in response:
                st.error(f"Error: {response['error']}")
            elif "data" in response and len(response["data"]) > 0:
                st.success(f"Successfully fetched {len(response['data'])} articles for {ticker.upper()}")
                
                # Convert to DataFrame for a nicer display
                df = pd.DataFrame(response["data"])
                
                # Display metrics summary
                avg_score = pd.to_numeric(df["Score"]).mean()
                st.subheader(f"Overall Sentiment: {'Bullish 🐂' if avg_score > 0.15 else 'Bearish 🐻' if avg_score < -0.15 else 'Neutral ⚖️'} ({avg_score:.2f})")
                
                # Display data as a table (without URLs for clean view, but we can make headlines clickable)
                st.subheader("Latest News Headlines")
                
                for _, row in df.iterrows():
                    with st.expander(f"{row['Sentiment']} ({row['Score']}) - {row['Headline']}"):
                        st.markdown(f"**Source:** {row['Source']}")
                        st.markdown(f"**Published:** {row['Published']}")
                        st.markdown(f"[Read Full Article]({row['URL']})")
                        
            else:
                st.warning(f"No news found for ticker {ticker.upper()}.")
    else:
        st.warning("Please enter a ticker symbol.")
else:
    st.info("👈 Enter a stock ticker in the sidebar and click 'Fetch News Sentiment' to begin.")
