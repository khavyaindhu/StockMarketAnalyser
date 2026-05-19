import streamlit as st
import pandas as pd
from api.alphavantage import get_news_sentiment, get_quote
from api.mediastack import get_india_news
from api.portfolio import PORTFOLIO, THEMES
from api.nifty50 import NIFTY_50
from api.glm5 import analyze_stock, analyze_theme, stream_chat
from api.angelone import fetch_all, is_configured

st.set_page_config(page_title="Stock Market Analyser", page_icon="📈", layout="wide")
st.title("📈 Stock Market Analyser — India Focus")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🗂 My Portfolio", "🌐 Theme Analysis",
    "🔍 Nifty 50 News", "🤖 AI Analysis", "💹 Angel One",
])


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
                df.style.map(color_change, subset=["Change"]),
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


# ── Tab 4: AI Analysis ─────────────────────────────────────────────────────────
with tab4:
    st.subheader("🤖 GLM-5 AI Analysis")
    st.caption("Powered by Llama 3.3 70B · via OpenRouter · Free model · No local setup needed")

    ai_tab1, ai_tab2, ai_tab3 = st.tabs(["📊 Portfolio Stock Analysis", "🌐 Theme Analysis", "💬 Ask AI"])

    # ── AI Sub-tab 1: Portfolio stock analysis ──────────────────────────────────
    with ai_tab1:
        st.markdown("Select a stock from your portfolio to get a GLM-5 generated analysis based on live news and sentiment.")

        stock_choice = st.selectbox("Choose a portfolio stock", list(PORTFOLIO.keys()), key="ai_stock_select")

        if st.button("Generate AI Analysis", type="primary", key="ai_stock_btn"):
            info = PORTFOLIO[stock_choice]
            ticker = info["ticker"]

            with st.spinner(f"Fetching data for {stock_choice}..."):
                news_data = get_india_news(info["keywords"], limit=6)
                av_data = get_news_sentiment(ticker)

            news_list = news_data.get("data", [])
            sentiment_list = av_data.get("data", [])

            with st.spinner("GLM-5 is analysing..."):
                result = analyze_stock(stock_choice, ticker, news_list, sentiment_list)

            st.markdown(f"### Analysis: {stock_choice} ({ticker})")
            st.markdown(result)

    # ── AI Sub-tab 2: Theme AI analysis ────────────────────────────────────────
    with ai_tab2:
        st.markdown("Select a macro theme to get GLM-5's analysis of how it affects your portfolio.")

        theme_choice = st.selectbox("Choose a macro theme", list(THEMES.keys()), key="ai_theme_select")

        if st.button("Generate Theme Analysis", type="primary", key="ai_theme_btn"):
            theme = THEMES[theme_choice]

            with st.spinner(f"Fetching news for theme: {theme_choice}..."):
                theme_news = get_india_news(theme["keywords"], limit=8)

            affected = [
                name for name, info in PORTFOLIO.items()
                if info["sector"] in theme["affected_sectors"]
            ]

            with st.spinner("GLM-5 is analysing the macro theme..."):
                result = analyze_theme(
                    theme_choice,
                    theme["impact_note"],
                    theme_news.get("data", []),
                    affected,
                )

            st.markdown(f"### Macro Theme: {theme_choice}")
            if affected:
                st.caption(f"Affected portfolio stocks: {', '.join(affected)}")
            st.markdown(result)

    # ── AI Sub-tab 3: Free-form chat ────────────────────────────────────────────
    with ai_tab3:
        st.markdown("Ask GLM-5 anything about your portfolio, the Indian market, or investing strategy.")

        # Build a brief portfolio context string to inject into every message
        portfolio_context = "\n".join(
            f"- {name} ({info['ticker']}, sector: {info['sector']})"
            for name, info in PORTFOLIO.items()
        )

        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []

        # Display chat history
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        user_input = st.chat_input("Ask about your portfolio or the Indian market...")

        if user_input:
            st.session_state.chat_history.append({"role": "user", "content": user_input})
            with st.chat_message("user"):
                st.markdown(user_input)

            system_msg = {
                "role": "system",
                "content": (
                    "You are a financial assistant specializing in Indian stock markets. "
                    f"The user's portfolio:\n{portfolio_context}\n"
                    "Answer concisely and specifically. Focus on Indian market dynamics."
                ),
            }

            messages_to_send = [system_msg] + st.session_state.chat_history

            with st.chat_message("assistant"):
                response_placeholder = st.empty()
                full_response = ""
                for chunk in stream_chat(messages_to_send):
                    full_response += chunk
                    response_placeholder.markdown(full_response + "▌")
                response_placeholder.markdown(full_response)

            st.session_state.chat_history.append({"role": "assistant", "content": full_response})

        if st.session_state.chat_history:
            if st.button("Clear Chat", key="clear_chat"):
                st.session_state.chat_history = []
                st.rerun()


# ── Tab 5: Angel One Live Data ─────────────────────────────────────────────────
with tab5:
    st.subheader("💹 Angel One — Live Trading Data")

    # ── Config check ───────────────────────────────────────────────────────────
    if not is_configured():
        st.error("Angel One credentials are not configured.")
        st.markdown("""
**Steps to set up:**

1. Create an app at [smartapi.angelone.in](https://smartapi.angelone.in) and copy your **API Key**
2. Open `.env` in this project and fill in:
```
ANGELONE_API_KEY=your_api_key
ANGELONE_CLIENT_CODE=your_client_code   # e.g. R123456
ANGELONE_PASSWORD=your_pin              # 4-digit trading PIN
ANGELONE_TOTP_SECRET=your_totp_secret   # base32 secret from Angel One TOTP setup
```
3. To get the **TOTP secret**: Angel One App → My Profile → Account Security → Enable TOTP
   → tap "Can't scan QR?" → copy the base32 secret shown
4. Restart this app after editing `.env`
        """)
        st.stop()

    # ── Fetch button ───────────────────────────────────────────────────────────
    col_btn, col_status = st.columns([1, 3])
    with col_btn:
        fetch_ao = st.button("🔄 Fetch from Angel One", type="primary", key="ao_fetch")
    with col_status:
        if "ao_fetched" in st.session_state:
            st.caption(f"Last fetched at {st.session_state.get('ao_fetch_time', '—')}")

    if fetch_ao:
        import datetime
        with st.spinner("Authenticating and fetching data from Angel One…"):
            result = fetch_all()
            st.session_state["ao_profile"]   = result["profile"]
            st.session_state["ao_funds"]     = result["funds"]
            st.session_state["ao_trades"]    = result["trades"]
            st.session_state["ao_orders"]    = result["orders"]
            st.session_state["ao_holdings"]  = result["holdings"]
            st.session_state["ao_positions"] = result["positions"]
            st.session_state["ao_fetched"]   = True
            st.session_state["ao_fetch_time"] = datetime.datetime.now().strftime("%H:%M:%S")

        # Surface auth error prominently
        first_error = result["profile"]["error"]
        if first_error:
            st.error(f"Authentication failed: {first_error}")
            _hint = ""
            if "base32" in first_error.lower() or "totp" in first_error.lower():
                _hint = (
                    "**TOTP secret issue:** Open `.env` and check `ANGELONE_TOTP_SECRET`. "
                    "It must be A-Z and 2-7 only (no spaces, no special chars, no 0/1/8/9). "
                    "Tip: In Angel One app → My Profile → Account Security → View TOTP secret."
                )
            elif "login failed" in first_error.lower() or "invalid" in first_error.lower():
                _hint = (
                    "**Login failed:** Double-check `ANGELONE_CLIENT_CODE` (e.g. R123456), "
                    "`ANGELONE_PASSWORD` (your 4-digit trading PIN), and "
                    "`ANGELONE_API_KEY` (from smartapi.angelone.in → Apps)."
                )
            elif "not installed" in first_error.lower():
                _hint = "**Missing package:** Run `pip install smartapi-python pyotp websocket-client` in the terminal."
            elif "rate" in first_error.lower():
                _hint = "**Rate limit:** Wait 30 seconds and try fetching again."
            if _hint:
                st.info(_hint)
        else:
            st.success("Data fetched successfully.")

    if "ao_fetched" not in st.session_state:
        st.info("Click **Fetch from Angel One** to load your live trading data.")
        st.stop()

    # ── Helper: error banner ───────────────────────────────────────────────────
    def _ao_error(result: dict, label: str):
        if not result["status"]:
            st.error(f"{label} error: {result['error']}")
            return True
        return False

    # ── Helper: color P&L cells ────────────────────────────────────────────────
    def _color_pnl(val):
        try:
            return "color: #22c55e" if float(val) >= 0 else "color: #ef4444"
        except (TypeError, ValueError):
            return ""

    # ── Sub-tabs ───────────────────────────────────────────────────────────────
    ao1, ao2, ao3, ao4, ao5 = st.tabs([
        "👤 Account & Funds",
        "📋 Trade Book",
        "📒 Order Book",
        "🏦 Holdings",
        "📊 Positions",
    ])

    # ── AO Sub-tab 1: Account & Funds ──────────────────────────────────────────
    with ao1:
        profile_res = st.session_state["ao_profile"]
        funds_res   = st.session_state["ao_funds"]

        col_p, col_f = st.columns(2)

        with col_p:
            st.markdown("#### Profile")
            if not _ao_error(profile_res, "Profile"):
                p = profile_res["data"]
                st.markdown(f"**Name:** {p.get('name', '—')}")
                st.markdown(f"**Email:** {p.get('email', '—')}")
                st.markdown(f"**Mobile:** {p.get('mobileNo', '—')}")
                st.markdown(f"**Client Code:** {p.get('clientcode', '—')}")
                exchanges = p.get('exchanges', [])
                products  = p.get('products', [])
                if exchanges:
                    st.markdown(f"**Exchanges enabled:** {', '.join(exchanges)}")
                if products:
                    st.markdown(f"**Products enabled:** {', '.join(products)}")

        with col_f:
            st.markdown("#### Funds & Margins")
            if not _ao_error(funds_res, "Funds"):
                f = funds_res["data"]
                fund_rows = [
                    ("Net Available (₹)",          f.get("net", "—")),
                    ("Available Cash (₹)",          f.get("availablecash", "—")),
                    ("Available Cash Margin (₹)",   f.get("availablecashmargain", "—")),
                    ("Collateral (₹)",              f.get("collateral", "—")),
                    ("Utilised Debits (₹)",         f.get("utiliseddebits", "—")),
                    ("M2M Realised (₹)",            f.get("m2mrealized", "—")),
                    ("M2M Unrealised (₹)",          f.get("m2munrealized", "—")),
                ]
                funds_df = pd.DataFrame(fund_rows, columns=["Item", "Value"])
                st.dataframe(funds_df, use_container_width=True, hide_index=True)

    # ── AO Sub-tab 2: Trade Book ───────────────────────────────────────────────
    with ao2:
        st.markdown("#### Today's Executed Trades")
        st.caption("Only filled orders appear here. Refreshes with each Fetch.")
        trades_res = st.session_state["ao_trades"]
        if not _ao_error(trades_res, "Trade Book"):
            data = trades_res["data"]
            if not data:
                st.info("No executed trades today.")
            else:
                TRADE_COLS = {
                    "tradingsymbol":  "Symbol",
                    "exchange":       "Exchange",
                    "transactiontype":"Side",
                    "producttype":    "Product",
                    "quantity":       "Qty",
                    "price":          "Price ₹",
                    "tradevalue":     "Value ₹",
                    "tradetime":      "Trade Time",
                    "orderid":        "Order ID",
                }
                df = pd.DataFrame(data)
                present = {k: v for k, v in TRADE_COLS.items() if k in df.columns}
                df = df[list(present.keys())].rename(columns=present)

                def _color_side(val):
                    if str(val).upper() == "BUY":  return "color: #22c55e"
                    if str(val).upper() == "SELL": return "color: #ef4444"
                    return ""

                styled = df.style
                if "Side" in df.columns:
                    styled = styled.map(_color_side, subset=["Side"])

                st.dataframe(styled, use_container_width=True, hide_index=True)
                st.caption(f"{len(df)} trade(s) executed today")

    # ── AO Sub-tab 3: Order Book ───────────────────────────────────────────────
    with ao3:
        st.markdown("#### Today's Orders")
        st.caption("Includes pending, executed, cancelled, and rejected orders.")
        orders_res = st.session_state["ao_orders"]
        if not _ao_error(orders_res, "Order Book"):
            data = orders_res["data"]
            if not data:
                st.info("No orders placed today.")
            else:
                ORDER_COLS = {
                    "tradingsymbol":  "Symbol",
                    "exchange":       "Exchange",
                    "transactiontype":"Side",
                    "producttype":    "Product",
                    "quantity":       "Qty",
                    "price":          "Price ₹",
                    "orderstatus":    "Status",
                    "text":           "Reason",
                    "orderid":        "Order ID",
                    "updatetime":     "Updated",
                }
                df = pd.DataFrame(data)
                present = {k: v for k, v in ORDER_COLS.items() if k in df.columns}
                df = df[list(present.keys())].rename(columns=present)

                def _color_status(val):
                    v = str(val).upper()
                    if "COMPLETE" in v: return "color: #22c55e"
                    if "REJECT" in v or "CANCEL" in v: return "color: #ef4444"
                    if "OPEN" in v or "PENDING" in v:  return "color: #f59e0b"
                    return ""

                styled = df.style
                if "Status" in df.columns:
                    styled = styled.map(_color_status, subset=["Status"])

                st.dataframe(styled, use_container_width=True, hide_index=True)

                # Summary badge row
                statuses = [str(r.get("orderstatus", "")).upper() for r in data]
                n_done    = sum(1 for s in statuses if "COMPLETE" in s)
                n_open    = sum(1 for s in statuses if "OPEN" in s or "PENDING" in s)
                n_cancel  = sum(1 for s in statuses if "CANCEL" in s or "REJECT" in s)
                c1, c2, c3 = st.columns(3)
                c1.metric("✅ Executed", n_done)
                c2.metric("⏳ Open / Pending", n_open)
                c3.metric("❌ Cancelled / Rejected", n_cancel)

    # ── AO Sub-tab 4: Holdings ─────────────────────────────────────────────────
    with ao4:
        st.markdown("#### Demat Holdings")
        st.caption("Long-term holdings held in your demat account.")
        holdings_res = st.session_state["ao_holdings"]
        if not _ao_error(holdings_res, "Holdings"):
            data = holdings_res["data"]
            if not data:
                st.info("No holdings found.")
            else:
                HOLD_COLS = {
                    "tradingsymbol": "Symbol",
                    "exchange":      "Exchange",
                    "quantity":      "Qty",
                    "averageprice":  "Avg Price ₹",
                    "ltp":           "LTP ₹",
                    "close":         "Prev Close ₹",
                    "pnl":           "P&L ₹",
                    "producttype":   "Product",
                    "isin":          "ISIN",
                }
                df = pd.DataFrame(data)
                present = {k: v for k, v in HOLD_COLS.items() if k in df.columns}
                df = df[list(present.keys())].rename(columns=present)

                # Coerce numeric
                for col in ["Avg Price ₹", "LTP ₹", "P&L ₹", "Prev Close ₹"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")

                styled = df.style.format(
                    {c: "{:.2f}" for c in ["Avg Price ₹", "LTP ₹", "P&L ₹", "Prev Close ₹"] if c in df.columns}
                )
                if "P&L ₹" in df.columns:
                    styled = styled.map(_color_pnl, subset=["P&L ₹"])

                st.dataframe(styled, use_container_width=True, hide_index=True)

                # Portfolio summary
                if "P&L ₹" in df.columns:
                    total_pnl = df["P&L ₹"].sum()
                    winners   = (df["P&L ₹"] > 0).sum()
                    losers    = (df["P&L ₹"] < 0).sum()
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Total Stocks", len(df))
                    c2.metric("Total P&L ₹", f"{total_pnl:,.2f}", delta=f"{total_pnl:+.2f}")
                    c3.metric("🟢 Winners", int(winners))
                    c4.metric("🔴 Losers", int(losers))

    # ── AO Sub-tab 5: Positions ────────────────────────────────────────────────
    with ao5:
        st.markdown("#### Open Positions")
        st.caption("Intraday (MIS) and carry-forward (CNC/NRML) open positions.")
        positions_res = st.session_state["ao_positions"]
        if not _ao_error(positions_res, "Positions"):
            data = positions_res["data"]
            if not data:
                st.info("No open positions.")
            else:
                POS_COLS = {
                    "tradingsymbol": "Symbol",
                    "exchange":      "Exchange",
                    "producttype":   "Product",
                    "netqty":        "Net Qty",
                    "netprice":      "Avg Price ₹",
                    "ltp":           "LTP ₹",
                    "close":         "Prev Close ₹",
                    "unrealised":    "Unrealised P&L ₹",
                    "realised":      "Realised P&L ₹",
                    "pnl":           "Total P&L ₹",
                }
                df = pd.DataFrame(data)
                present = {k: v for k, v in POS_COLS.items() if k in df.columns}
                df = df[list(present.keys())].rename(columns=present)

                pnl_cols = [c for c in ["Unrealised P&L ₹", "Realised P&L ₹", "Total P&L ₹"] if c in df.columns]
                price_cols = [c for c in ["Avg Price ₹", "LTP ₹", "Prev Close ₹"] if c in df.columns]

                for col in pnl_cols + price_cols:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

                styled = df.style.format(
                    {c: "{:.2f}" for c in pnl_cols + price_cols}
                )
                for col in pnl_cols:
                    styled = styled.map(_color_pnl, subset=[col])

                st.dataframe(styled, use_container_width=True, hide_index=True)

                if "Total P&L ₹" in df.columns:
                    total = df["Total P&L ₹"].sum()
                    st.metric("Total Open P&L ₹", f"{total:,.2f}", delta=f"{total:+.2f}")
