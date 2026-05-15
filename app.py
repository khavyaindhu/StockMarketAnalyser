import streamlit as st
import pandas as pd
from api.alphavantage import get_news_sentiment, get_quote
from api.mediastack import get_india_news
from api.portfolio import PORTFOLIO, THEMES
from api.nifty50 import NIFTY_50

st.set_page_config(page_title="Stock Market Analyser", page_icon="📈", layout="wide")
st.title("📈 Stock Market Analyser — India Focus")

tab1, tab2, tab3 = st.tabs(["🗂 My Portfolio", "🌐 Theme Analysis", "🔍 Nifty 50 News"])


# ── Tab 1: My Portfolio ────────────────────────────────────────────────────────
with tab1:
    st.subheader("My Portfolio — News & Market Impact")
    st.caption("News from Mediastack · Sentiment & price from AlphaVantage")

    for name, info in PORTFOLIO.items():
        ticker = info["ticker"]
        with st.expander(f"**{name}** ({ticker})  |  Sector: {info['sector']}", expanded=True):
            col_news, col_price = st.columns([2, 1])

            with col_price:
                st.markdown("**Live Quote**")
                with st.spinner("Fetching price..."):
                    quote = get_quote(ticker)
                if "error" in quote:
                    st.warning(quote["error"])
                else:
                    change_pct = quote["change_percent"].replace("%", "").strip()
                    try:
                        val = float(change_pct)
                        color = "🟢" if val >= 0 else "🔴"
                        st.metric(
                            label=f"{ticker}",
                            value=f"₹ {float(quote['price']):.2f}",
                            delta=f"{quote['change_percent']}",
                        )
                    except ValueError:
                        st.write(f"Price: {quote['price']}")

                st.markdown("**AlphaVantage Sentiment**")
                with st.spinner("Fetching sentiment..."):
                    av = get_news_sentiment(ticker)
                if "error" in av:
                    st.warning(av["error"])
                elif av.get("data"):
                    scores = []
                    for a in av["data"][:5]:
                        score = a.get("Score", 0)
                        try:
                            scores.append(float(score))
                        except (ValueError, TypeError):
                            pass
                    if scores:
                        avg = sum(scores) / len(scores)
                        label = "Bullish 🐂" if avg > 0.15 else "Bearish 🐻" if avg < -0.15 else "Neutral ⚖️"
                        st.metric("Avg Sentiment Score", f"{avg:.3f}", delta=label)
                else:
                    st.info("No AV sentiment data.")

            with col_news:
                st.markdown("**Latest News (Mediastack)**")
                with st.spinner("Fetching news..."):
                    news = get_india_news(info["keywords"], limit=6)
                if "error" in news:
                    st.warning(news["error"])
                elif news.get("data"):
                    for article in news["data"]:
                        st.markdown(
                            f"- [{article['title']}]({article['url']})  \n"
                            f"  <small>📰 {article['source']} &nbsp;·&nbsp; {article['published_at'][:10] if article['published_at'] else ''}</small>",
                            unsafe_allow_html=True,
                        )
                else:
                    st.info("No news found for this stock.")


# ── Tab 2: Theme Analysis ──────────────────────────────────────────────────────
with tab2:
    st.subheader("Macro Theme → Portfolio Impact")
    st.caption("Select a global/macro event to see how it affects your holdings")

    theme_name = st.selectbox("Select a Theme / Macro Event", list(THEMES.keys()))
    theme = THEMES[theme_name]

    st.info(f"**Impact logic:** {theme['impact_note']}")

    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.markdown("**Related News Headlines** (Mediastack)")
        with st.spinner("Fetching theme news..."):
            news = get_india_news(theme["keywords"], limit=8)
        if "error" in news:
            st.warning(news["error"])
        elif news.get("data"):
            for article in news["data"]:
                sentiment_hint = ""
                title_lower = article["title"].lower()
                if any(w in title_lower for w in ["rise", "surge", "gain", "up", "boost", "high"]):
                    sentiment_hint = "🟢 "
                elif any(w in title_lower for w in ["fall", "drop", "down", "loss", "weak", "cut"]):
                    sentiment_hint = "🔴 "
                st.markdown(
                    f"{sentiment_hint}[{article['title']}]({article['url']})  \n"
                    f"<small>{article['source']} · {article['published_at'][:10] if article['published_at'] else ''}</small>",
                    unsafe_allow_html=True,
                )
        else:
            st.info("No news found for this theme.")

    with col_right:
        st.markdown("**Affected Portfolio Stocks**")
        affected = {
            name: info
            for name, info in PORTFOLIO.items()
            if info["sector"] in theme["affected_sectors"]
        }
        if not affected:
            st.info("None of your portfolio stocks are in the affected sectors for this theme.")
        else:
            rows = []
            for name, info in affected.items():
                quote = get_quote(info["ticker"])
                if "error" not in quote:
                    rows.append({
                        "Stock": name,
                        "Ticker": info["ticker"],
                        "Price (₹)": quote["price"],
                        "Change": quote["change_percent"],
                    })
                else:
                    rows.append({
                        "Stock": name,
                        "Ticker": info["ticker"],
                        "Price (₹)": "—",
                        "Change": "—",
                    })

            df = pd.DataFrame(rows)

            def color_change(val):
                try:
                    v = float(str(val).replace("%", "").strip())
                    return "color: green" if v >= 0 else "color: red"
                except ValueError:
                    return ""

            st.dataframe(
                df.style.applymap(color_change, subset=["Change"]),
                use_container_width=True,
                hide_index=True,
            )

            st.markdown("**News for Affected Stocks**")
            for name, info in affected.items():
                with st.expander(name):
                    n = get_india_news(info["keywords"], limit=4)
                    if n.get("data"):
                        for a in n["data"]:
                            st.markdown(f"- [{a['title']}]({a['url']})", unsafe_allow_html=True)
                    else:
                        st.info("No recent news.")


# ── Tab 3: Nifty 50 News ───────────────────────────────────────────────────────
with tab3:
    st.subheader("Nifty 50 — News & Sentiment")

    col_s, col_m = st.columns([1, 2])
    with col_s:
        mode = st.radio("Select by", ["Nifty 50 Dropdown", "Custom Ticker"], horizontal=True)
        if mode == "Nifty 50 Dropdown":
            company = st.selectbox("Stock", list(NIFTY_50.keys()))
            ticker = NIFTY_50[company]
            st.caption(f"Ticker: `{ticker}`")
        else:
            ticker = st.text_input("Enter BSE ticker (e.g. RELIANCE.BSE)", value="RELIANCE.BSE")

        fetch = st.button("Analyse", type="primary")

    if fetch:
        with col_m:
            st.markdown(f"### {ticker}")
            q = get_quote(ticker)
            if "error" not in q:
                st.metric("Price", f"₹ {float(q['price']):.2f}", delta=q["change_percent"])

            st.markdown("**News (Mediastack)**")
            kw = [ticker.split(".")[0]]
            mn = get_india_news(kw, limit=8)
            if mn.get("data"):
                for a in mn["data"]:
                    st.markdown(f"- [{a['title']}]({a['url']})", unsafe_allow_html=True)
            else:
                st.info("No Mediastack news found.")

            st.markdown("**Sentiment (AlphaVantage)**")
            av = get_news_sentiment(ticker)
            if av.get("data"):
                df = pd.DataFrame(av["data"])
                st.dataframe(
                    df[["Headline", "Sentiment", "Score", "Source", "Published"]],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No AlphaVantage sentiment data.")
