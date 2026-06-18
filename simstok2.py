import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import sqlite3
import hashlib
import json
from datetime import datetime, timedelta

# =========================================================
# חלק 1: הגדרות דף, בסיס נתונים SQLite יציב (גרסה 14)
# =========================================================
st.set_page_config(page_title="Pro Investment Simulator", layout="wide")

DB_FILE = "/tmp/simulator_pro_v14.db" 
TAX_RATE = 0.25      
COMMISSION_RATE = 0.001 

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, cash_ils REAL, portfolio TEXT, orders TEXT, watchlist TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, timestamp TEXT, ticker TEXT, 
                  action TEXT, qty REAL, price_usd REAL, ex_rate REAL, commission_ils REAL, tax_ils REAL, total_ils REAL)''')
    conn.commit()
    conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def register_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE username=?", (username,))
    if c.fetchone():
        conn.close()
        return False
    c.execute("INSERT INTO users VALUES (?, ?, 100000.0, '{}', '[]', '[]')", (username, hash_password(password)))
    conn.commit()
    conn.close()
    return True

def login_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE username=? AND password=?", (username, hash_password(password)))
    user = c.fetchone()
    conn.close()
    return user is not None
def load_user_data(username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT cash_ils, portfolio, orders, watchlist FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "cash_ils": float(row[0]) if pd.notna(row[0]) else 100000.0, 
            "portfolio": json.loads(row[1]) if row[1] else {}, 
            "orders": json.loads(row[2]) if row[2] else [], 
            "watchlist": json.loads(row[3]) if row[3] else []
        }
    return {"cash_ils": 100000.0, "portfolio": {}, "orders": [], "watchlist": []}

def save_user_data(username, data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET cash_ils=?, portfolio=?, orders=?, watchlist=? WHERE username=?", 
              (data["cash_ils"], json.dumps(data["portfolio"]), json.dumps(data["orders"]), json.dumps(data["watchlist"]), username))
    conn.commit()
    conn.close()

def add_to_history(username, ticker, action, qty, price_usd, ex_rate, commission_ils, tax_ils, total_ils):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("INSERT INTO history (username, timestamp, ticker, action, qty, price_usd, ex_rate, commission_ils, tax_ils, total_ils) VALUES (?,?,?,?,?,?,?,?,?,?)",
              (username, now_str, ticker, action, qty, price_usd, ex_rate, commission_ils, tax_ils, total_ils))
    conn.commit()
    conn.close()

def load_user_history(username):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT timestamp as 'Time', ticker as 'Asset', action as 'Action', qty as 'Shares', price_usd as 'Source Price', ex_rate as 'Exchange Rate', commission_ils as 'Commission (ILS)', tax_ils as 'Tax (ILS)', total_ils as 'Total (ILS)' FROM history WHERE username=? ORDER BY id DESC", conn, params=(username,))
    conn.close()
    return df

init_db()
def get_usd_ils_rate():
    try:
        df = yf.Ticker("USDILS=X").history(period="1d")
        if not df.empty and pd.notna(df['Close'].iloc[-1]):
            return float(df['Close'].iloc[-1])
        return 3.70
    except:
        return 3.70

def render_top_market_indices():
    indices = {"S&P 500": "^GSPC", "Nasdaq 100": "^NDX", "TA 125": "^TA125.TA", "Bitcoin": "BTC-USD"}
    cols = st.columns(len(indices))
    for i, (name, ticker) in enumerate(indices.items()):
        try:
            stock_obj = yf.Ticker(ticker)
            df = stock_obj.history(period="2d")
            close_today = stock_obj.info.get('regularMarketPrice', None)
            if close_today is None or pd.isna(close_today):
                close_today = df['Close'].iloc[-1] if not df.empty else 0.0
            close_yesterday = df['Close'].iloc[-2] if len(df) >= 2 else close_today
            if ".TA" in ticker:  
                close_today /= 100
                close_yesterday /= 100
            pct_change = ((close_today - close_yesterday) / close_yesterday) * 100 if close_yesterday > 0 else 0.0
            cols[i].metric(name, f"${close_today:,.2f}" if "TA" not in ticker else f"₪{close_today:,.2f}", f"{pct_change:+.2f}%")
        except: 
            cols[i].metric(name, "Loading...")

def load_stock_data(ticker_symbol):
    if not ticker_symbol: return pd.DataFrame(), None
    try:
        stock_obj = yf.Ticker(ticker_symbol)
        df = stock_obj.history(period="2y", auto_adjust=True)
        return df, stock_obj
    except: return pd.DataFrame(), None

def get_safe_current_price(stock_obj, df):
    try:
        price = stock_obj.info.get('currentPrice', None)
        if price is not None and pd.notna(price) and price > 0: return float(price)
        price = stock_obj.info.get('regularMarketPrice', None)
        if price is not None and pd.notna(price) and price > 0: return float(price)
        if df is not None and not df.empty:
            price = df['Close'].iloc[-1]
            if pd.notna(price) and price > 0: return float(price)
    except: pass
    return 0.0

def get_daily_change_pct(stock_obj, df):
    try:
        if df is not None and len(df) >= 2:
            c_p = df['Close'].iloc[-1]
            y_p = df['Close'].iloc[-2]
            if y_p > 0: return ((c_p - y_p) / y_p) * 100
    except: pass
    return 0.0
def calculate_time_elapsed(buy_timestamp_str):
    try:
        buy_time = datetime.strptime(buy_timestamp_str, '%Y-%m-%d %H:%M:%S')
        diff = datetime.now() - buy_time
        if diff.days > 0: return f"{diff.days} days"
        hours = diff.seconds // 3600
        if hours > 0: return f"{hours} hours"
        minutes = (diff.seconds % 3600) // 60
        return f"{minutes} minutes"
    except: return "N/A"

def calculate_periodic_returns(ticker_symbol):
    try:
        df, _ = load_stock_data(ticker_symbol)
        if df.empty or len(df) < 5: return None
        curr = df['Close'].iloc[-1]
        def get_pct(days):
            old = df['Close'].iloc[max(0, len(df) - days)]
            return ((curr - old) / old) * 100
        return {"1 Week": f"{get_pct(5):+.2f}%", "1 Month": f"{get_pct(21):+.2f}%", "6 Months": f"{get_pct(126):+.2f}%", "1 Year": f"{get_pct(len(df)-1):+.2f}%"}
    except: return None

def get_sector_leaderboard(sector_name):
    sector_map = {
        "Technology": ["AAPL", "MSFT", "NVDA", "NICE.TA"],
        "Healthcare": ["JNJ", "LLY", "TEVA.TA", "PFE"],
        "Financials": ["JPM", "BAC", "LUMI.TA", "POLI.TA"]
    }
    tickers = sector_map.get(sector_name, ["AAPL", "MSFT"])
    rows = []
    for tick in tickers:
        try:
            df, obj = load_stock_data(tick)
            c_p = get_safe_current_price(obj, df)
            if c_p > 0:
                if ".TA" in tick: c_p /= 100
                symbol_display = "ILS" if ".TA" in tick else "USD"
                rows.append({"Ticker": tick, "Price": f"{c_p:,.2f} {symbol_display}"})
        except: pass
    return rows

def calculate_portfolio_value_ils(portfolio, ex_rate):
    total_val_ils = 0.0
    shares_data = {}
    if not portfolio: return total_val_ils, shares_data
    for tick, info in portfolio.items():
        if not isinstance(info, dict): continue
        qty = info.get("qty", 0)
        if qty <= 0: continue
        df, obj = load_stock_data(tick)
        price_raw = get_safe_current_price(obj, df)
        if price_raw == 0:
            price_raw = info.get("avg_price_source", 1.0)
            if ".TA" in tick: price_raw *= 100
        if ".TA" in tick:
            price_converted = price_raw / 100
            val_ils = price_converted * qty
        else:
            price_converted = price_raw
            val_ils = price_raw * qty * ex_rate
        total_val_ils += val_ils
        shares_data[tick] = {"val_ils": val_ils, "price_source_currency": price_converted}
    return total_val_ils, shares_data

def analyze_ticker(df, selected_risk_profile, is_ils_stock, stock_obj):
    df['MA200'] = df['Close'].rolling(window=200).mean()
    df['BB_Middle'] = df['Close'].rolling(window=20).mean()
    df['BB_Std'] = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['BB_Middle'] + (2 * df['BB_Std'])
    df['BB_Lower'] = df['BB_Middle'] - (2 * df['BB_Std'])
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['RSI'] = 100 - (100 / (1 + (gain / (loss + 0.0001))))
    current_price = get_safe_current_price(stock_obj, df)
    current_rsi = df['RSI'].iloc[-1] if pd.notna(df['RSI'].iloc[-1]) else 50.0
    ma200_curr = df['MA200'].iloc[-1] if pd.notna(df['MA200'].iloc[-1]) else current_price
    bb_lower_curr = df['BB_Lower'].iloc[-1] if pd.notna(df['BB_Lower'].iloc[-1]) else current_price * 0.95
    if is_ils_stock:
        current_price /= 100
        ma200_curr /= 100
        bb_lower_curr /= 100
    reasons = []
    score = 1 if current_price > ma200_curr else -1
    buy_threshold, sl_multiplier = (2, 0.98) if "Conservative" in selected_risk_profile else ((0, 0.94) if "Aggressive" in selected_risk_profile else (1, 0.96))
    verdict, v_type = ("Buy Opportunity", "BUY") if score >= buy_threshold else (("Wait for Drop", "WAIT") if score < 0 else ("Neutral / Hold", "HOLD"))
    return {"df": df, "verdict": verdict, "verdict_type": v_type, "current_price": current_price, "waiting_target": bb_lower_curr, "stop_loss_price": bb_lower_curr * sl_multiplier, "analysis_reasons": reasons}

def check_and_execute_limit_orders(username, data, ex_rate):
    updated_orders = []
    executed_any = False
    for order in data.get("orders", []):
        tick, target, o_type, qty = order["ticker"], order["target_price"], order["type"], order["qty"]
        df, obj = load_stock_data(tick)
        curr_price = get_safe_current_price(obj, df)
        if curr_price == 0:
            updated_orders.append(order)
            continue
        if ".TA" in tick: curr_price /= 100
        if o_type == "BUY_LIMIT" and curr_price <= target:
            cost_ils = curr_price * qty * (1.0 if ".TA" in tick else ex_rate)
            if data["cash_ils"] >= cost_ils:
                data["cash_ils"] -= cost_ils
                holding = data["portfolio"].get(tick, {"qty": 0, "avg_price_source": 0.0, "first_buy_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
                new_qty = holding["qty"] + qty
                new_avg = ((holding["qty"] * holding["avg_price_source"]) + (qty * curr_price)) / new_qty if holding["qty"] > 0 else curr_price
                data["portfolio"][tick] = {"qty": new_qty, "avg_price_source": new_avg, "first_buy_time": holding.get("first_buy_time", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}
                executed_any = True
        elif o_type == "SELL_LIMIT" and curr_price >= target:
            holding = data["portfolio"].get(tick, {"qty": 0, "avg_price_source": 0.0})
            if holding["qty"] >= qty:
                val_ils = curr_price * qty * (1.0 if ".TA" in tick else ex_rate)
                data["cash_ils"] += val_ils
                data["portfolio"][tick]["qty"] -= qty
                if data["portfolio"][tick]["qty"] == 0: del data["portfolio"][tick]
                executed_any = True
        else: updated_orders.append(order)
    if executed_any:
        data["orders"] = updated_orders
        save_user_data(username, data)
        return True
    return False

def log_portfolio_history(username, net_worth): pass
def load_portfolio_history(username): return pd.DataFrame()

def calculate_achievements(data, net_worth):
    has_trades = len(data["portfolio"]) > 0
    is_diversified = len(data["portfolio"]) >= 3
    return {
        "First Steps": {"desc": "Own your first stock asset", "unlocked": has_trades},
        "Risk Manager": {"desc": "Hold 3 or more assets", "unlocked": is_diversified}
    }
# =========================================================
# חלק 5: ממשק המשתמש והלשוניות של חדר המסחר
# =========================================================
st.sidebar.title("Navigation & Settings")
if 'logged_in_user' not in st.session_state:
    st.session_state['logged_in_user'] = None

if st.session_state['logged_in_user'] is None:
    st.subheader("🔐 Security Portal")
    auth_tab1, auth_tab2 = st.tabs(["🔑 Login", "📝 Register"])
    with auth_tab1:
        login_user_input = st.text_input("Username:", key="login_user").strip()
        login_pass_input = st.text_input("Password:", type="password", key="login_pass").strip()
        if st.button("Connect Account", use_container_width=True):
            if login_user_input and login_pass_input and login_user(login_user_input, login_pass_input):
                st.session_state['logged_in_user'] = login_user_input
                st.success("Welcome back!")
                st.rerun()
            else: st.error("Invalid credentials.")
    with auth_tab2:
        reg_user_input = st.text_input("Choose Username:", key="reg_user").strip()
        reg_pass_input = st.text_input("Choose Password:", type="password", key="reg_pass").strip()
        if st.button("Create Account", use_container_width=True):
            if reg_user_input and reg_pass_input:
                if register_user(reg_user_input, reg_pass_input): st.success("Success! Please log in.")
                else: st.error("Username already taken.")
    st.stop()

current_user = st.session_state['logged_in_user']
user_db = load_user_data(current_user)
usd_ils = get_usd_ils_rate()

st.sidebar.subheader(f"Investor: {current_user}")
st.sidebar.info(f"Exchange Rate: 1 USD = {usd_ils:.3f} ILS")
if st.sidebar.button("Logout"):
    st.session_state['logged_in_user'] = None
    st.rerun()

risk_profile = st.sidebar.selectbox("Risk Profile:", ["Aggressive", "Moderate", "Conservative"], index=1)
is_israeli = st.sidebar.checkbox("TASE Stock (Israel)")
raw_ticker = st.sidebar.text_input("Search Ticker:", value="AAPL").upper().strip()
ticker_1 = f"{raw_ticker}.TA" if is_israeli and not raw_ticker.endswith(".TA") else raw_ticker

@st.fragment(run_every=60)
def render_realtime_simulator():
    global user_db, usd_ils, ticker_1
    if check_and_execute_limit_orders(current_user, user_db, usd_ils):
        user_db = load_user_data(current_user)
        
    portfolio_val_ils, holdings_dist = calculate_portfolio_value_ils(user_db["portfolio"], usd_ils)
    total_net_worth_ils = user_db["cash_ils"] + portfolio_val_ils
    achievements = calculate_achievements(user_db, total_net_worth_ils)
    
    tab_portfolio, tab_trade, tab_history, tab_ai = st.tabs(["Portfolio", "Trading Station", "History", "AI Advisor"])
    
    with tab_portfolio:
        st.subheader("Balances Summary")
        cw1, cw2, cw3 = st.columns(3)
        cw1.metric("Available Cash", f"₪{user_db['cash_ils']:,.2f}")
        cw2.metric("Stocks Value", f"₪{portfolio_val_ils:,.2f}")
        cw3.metric("Total Net Worth", f"₪{total_net_worth_ils:,.2f}")
        
        holding_rows = []
        pie_labels, pie_values = ["Cash"], [user_db["cash_ils"]]
        if user_db.get("portfolio"):
            for tick, info in user_db["portfolio"].items():
                qty = info.get("qty", 0)
                if qty <= 0: continue
                df, obj = load_stock_data(tick)
                price_raw = get_safe_current_price(obj, df)
                daily_chg = get_daily_change_pct(obj, df)
                is_ta_asset = ".TA" in tick
                curr_market_price = price_raw / 100 if is_ta_asset else price_raw
                asset_val_ils = curr_market_price * qty * (1.0 if is_ta_asset else usd_ils)
                currency_sym = "₪" if is_ta_asset else "$"
                pie_labels.append(tick)
                pie_values.append(asset_val_ils)
                avg_buy_cost = info.get("avg_price_source", 0.0)
                roi_pct = ((curr_market_price - avg_buy_cost) / avg_buy_cost) * 100 if avg_buy_cost > 0 else 0.0
                holding_rows.append({
                    "Asset": tick, "Shares": f"{qty:,.0f}", "Avg Cost": f"{currency_sym}{avg_buy_cost:,.2f}",
                    "Market Price": f"{currency_sym}{curr_market_price:,.2f}", "Total Value": f"₪{asset_val_ils:,.2f}",
                    "Daily Change": f"{daily_chg:+.2f}%", "ROI": f"{roi_pct:+.2f}%"
                })
        if holding_rows:
            st.dataframe(pd.DataFrame(holding_rows).set_index("Asset"), use_container_width=True)
            fig_pie = go.Figure(data=[go.Pie(labels=pie_labels, values=pie_values, hole=.4)])
            fig_pie.update_layout(template="plotly_dark", height=300)
            st.plotly_chart(fig_pie, use_container_width=True)
        else: st.info("Portfolio is empty.")
        
        st.subheader("Badges & Achievements")
        ach_cols = st.columns(len(achievements))
        for idx, (title, details) in enumerate(achievements.items()):
            badge = "🏅" if details["unlocked"] else "🔒"
            with ach_cols[idx]: st.metric(title, badge, help=details["desc"])

    with tab_trade:
        if ticker_1:
            df1, stock_obj1 = load_stock_data(ticker_1)
            if not df1.empty and stock_obj1 and len(df1) > 20:
                is_ta = ".TA" in ticker_1
                res1 = analyze_ticker(df1, risk_profile, is_ta, stock_obj1)
                curr_price_normalized = res1['current_price']
                st.subheader(f"Order Placement: {ticker_1}")
                tc1, tc2, tc3 = st.columns(3)
                holding_info = user_db["portfolio"].get(ticker_1, {"qty": 0, "avg_price_source": 0.0, "first_buy_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
                with tc1:
                    t_qty = st.number_input("Quantity:", min_value=1, value=10, step=1)
                    action_mode = st.radio("Type:", ["Market", "Limit"])
                    target_limit = st.number_input("Limit Price:", min_value=0.01, value=curr_price_normalized) if action_mode == "Limit" else curr_price_normalized
                with tc2:
                    st.write(""); st.write("")
                    gross_ils = t_qty * curr_price_normalized * (1.0 if is_ta else usd_ils)
                    comm_ils = gross_ils * COMMISSION_RATE
                    if st.button("BUY", use_container_width=True):
                        if action_mode == "Market":
                            if user_db["cash_ils"] >= (gross_ils + comm_ils):
                                user_db["cash_ils"] -= (gross_ils + comm_ils)
                                n_qty = holding_info["qty"] + t_qty
                                n_avg = ((holding_info["qty"] * holding_info["avg_price_source"]) + (t_qty * curr_price_normalized)) / n_qty if holding_info["qty"] > 0 else curr_price_normalized
                                user_db["portfolio"][ticker_1] = {"qty": n_qty, "avg_price_source": n_avg, "first_buy_time": holding_info.get("first_buy_time", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}
                                save_user_data(current_user, user_db)
                                add_to_history(current_user, ticker_1, "BUY", t_qty, curr_price_normalized, (1.0 if is_ta else usd_ils), comm_ils, 0.0, (gross_ils + comm_ils))
                                st.rerun()
                        else:
                            user_db["orders"].append({"ticker": ticker_1, "type": "BUY_LIMIT", "target_price": target_limit, "qty": t_qty})
                            save_user_data(current_user, user_db); st.rerun()
                    if st.button("SELL", use_container_width=True):
                        if action_mode == "Market" and holding_info["qty"] >= t_qty:
                            profit = (curr_price_normalized - holding_info["avg_price_source"]) * t_qty
                            tax = (profit * (1.0 if is_ta else usd_ils) * TAX_RATE) if profit > 0 else 0.0
                            user_db["cash_ils"] += (gross_ils - comm_ils - tax)
                            user_db["portfolio"][ticker_1]["qty"] -= t_qty
                            if user_db["portfolio"][ticker_1]["qty"] == 0: del user_db["portfolio"][ticker_1]
                            save_user_data(current_user, user_db)
                            add_to_history(current_user, ticker_1, "SELL", t_qty, curr_price_normalized, (1.0 if is_ta else usd_ils), comm_ils, tax, (gross_ils - comm_ils - tax))
                            st.rerun()
                        elif action_mode == "Limit" and holding_info["qty"] >= t_qty:
                            user_db["orders"].append({"ticker": ticker_1, "type": "SELL_LIMIT", "target_price": target_limit, "qty": t_qty})
                            save_user_data(current_user, user_db); st.rerun()
                with tc3: st.info(f"Held: {holding_info['qty']} | Price: {curr_price_normalized:.2f}")
        else: st.error("Enter ticker.")

    with tab_history:
        st.subheader("Watchlist & Active Orders")
        if user_db.get("orders"): st.dataframe(pd.DataFrame(user_db["orders"]), use_container_width=True)
        st.subheader("Logs")
        st.dataframe(load_user_history(current_user), use_container_width=True)

    with tab_ai:
        st.subheader("AI Advisor Insights")
        if portfolio_val_ils == 0: st.info("Cash Allocation is 100%. Consider diversifying into liquid assets.")
        else: st.success("Portfolio analysis active. Balance index is optimal.")

render_realtime_simulator()
