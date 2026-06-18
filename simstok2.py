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
# חלק 1: הגדרות דף, בסיס נתונים SQLite משולב ומאובטח
# =========================================================
DB_FILE = "/tmp/simulator_pro_final.db"  # בסיס נתונים נקי ויציב
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
    # טבלה חדשה וקבועה לשמירת היסטוריית שווי התיק לאורך זמן
    c.execute('''CREATE TABLE IF NOT EXISTS portfolio_history 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, timestamp TEXT, total_value REAL)''')
    conn.commit()
    conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def register_user(username, password):
    try:
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
    except:
        return False

def login_user(username, password):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT username FROM users WHERE username=? AND password=?", (username, hash_password(password)))
        user = c.fetchone()
        conn.close()
        return user is not None
    except:
        return False

def load_user_data(username):
    try:
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
    except:
        pass
    return {"cash_ils": 100000.0, "portfolio": {}, "orders": [], "watchlist": []}

def save_user_data(username, data):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE users SET cash_ils=?, portfolio=?, orders=?, watchlist=? WHERE username=?", 
                  (data["cash_ils"], json.dumps(data["portfolio"]), json.dumps(data["orders"]), json.dumps(data["watchlist"]), username))
        conn.commit()
        conn.close()
    except:
        pass

def add_to_history(username, ticker, action, qty, price_usd, ex_rate, commission_ils, tax_ils, total_ils):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute("INSERT INTO history (username, timestamp, ticker, action, qty, price_usd, ex_rate, commission_ils, tax_ils, total_ils) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (username, now_str, ticker, action, qty, price_usd, ex_rate, commission_ils, tax_ils, total_ils))
        conn.commit()
        conn.close()
    except:
        pass

def load_user_history(username):
    try:
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql_query("SELECT timestamp as 'זמן', ticker as 'נכס', action as 'פעולה', qty as 'כמות', price_usd as 'מחיר מקור', ex_rate as 'שער המרה', commission_ils as 'עמלה (שח)', tax_ils as 'מס (שח)', total_ils as 'סך הכל (שח)' FROM history WHERE username=? ORDER BY id DESC", conn, params=(username,))
        conn.close()
        return df
    except:
        return pd.DataFrame()

def log_portfolio_history(username, total_value):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute("SELECT total_value FROM portfolio_history WHERE username=? ORDER BY id DESC LIMIT 1", (username,))
        last_row = c.fetchone()
        if last_row is None or abs(last_row[0] - total_value) > 10.0:
            c.execute("INSERT INTO portfolio_history (username, timestamp, total_value) VALUES (?, ?, ?)", (username, now_str, total_value))
            conn.commit()
        conn.close()
    except:
        pass

def load_portfolio_history(username):
    try:
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql_query("SELECT timestamp as 'זמן', total_value as '🌟 שווי תיק (₪)' FROM portfolio_history WHERE username=? ORDER BY id ASC", conn, params=(username,))
        conn.close()
        return df
    except:
        return pd.DataFrame()

init_db()
# =========================================================
# חלק 2: מנועי חישוב שוק, פקודות עתידיות והישגי מערכת
# =========================================================
def get_usd_ils_rate():
    try:
        df = yf.Ticker("USDILS=X").history(period="1d")
        if not df.empty and pd.notna(df['Close'].iloc[-1]):
            return float(df['Close'].iloc[-1])
    except:
        pass
    return 3.70

def load_stock_data(ticker_symbol):
    if not ticker_symbol: return pd.DataFrame(), None
    try:
        stock_obj = yf.Ticker(ticker_symbol)
        df = stock_obj.history(period="2y", auto_adjust=True)
        return df, stock_obj
    except: 
        return pd.DataFrame(), None

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
        if diff.days > 0: return f"{diff.days} ימים"
        hours = diff.seconds // 3600
        if hours > 0: return f"{hours} שעות"
        minutes = (diff.seconds % 3600) // 60
        return f"{minutes} דקות"
    except: return "N/A"

def calculate_periodic_returns(ticker_symbol):
    try:
        df, _ = load_stock_data(ticker_symbol)
        if df.empty or len(df) < 5: return None
        curr = df['Close'].iloc[-1]
        def get_pct(days):
            old = df['Close'].iloc[max(0, len(df) - days)]
            return ((curr - old) / old) * 100
        return {"שבוע אחרון": f"{get_pct(5):+.2f}%", "חודש אחרון": f"{get_pct(21):+.2f}%", "חצי שנה": f"{get_pct(126):+.2f}%", "שנה אחרונה": f"{get_pct(len(df)-1):+.2f}%"}
    except: return None

def get_sector_leaderboard(sector_name):
    sector_map = {
        "טכנולוגיה (Technology)": ["AAPL", "MSFT", "NVDA", "NICE.TA"],
        "בריאות (Healthcare)": ["JNJ", "LLY", "TEVA.TA", "PFE"],
        "פיננסים ובנקים (Financials)": ["JPM", "BAC", "LUMI.TA", "POLI.TA"]
    }
    tickers = sector_map.get(sector_name, ["AAPL", "MSFT"])
    rows = []
    for tick in tickers:
        try:
            df, obj = load_stock_data(tick)
            c_p = get_safe_current_price(obj, df)
            if c_p > 0:
                if ".TA" in tick: c_p /= 100
                symbol_display = "₪" if ".TA" in tick else "$"
                rows.append({"סימול": tick, "מחיר": f"{symbol_display}{c_p:,.2f}"})
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
    buy_threshold, sl_multiplier = (2, 0.98) if "סולידי" in selected_risk_profile else ((0, 0.94) if "אגרסיבי" in selected_risk_profile else (1, 0.96))
    verdict, v_type = ("הזדמנות קנייה (Buy)", "BUY") if score >= buy_threshold else (("להמתין לירידה (Wait)", "WAIT") if score < 0 else ("החזק / ניטרלי (Hold)", "HOLD"))
    return {"df": df, "verdict": verdict, "verdict_type": v_type, "current_price": current_price, "current_rsi": current_rsi, "waiting_target": bb_lower_curr, "stop_loss_price": bb_lower_curr * sl_multiplier, "analysis_reasons": reasons}

def check_and_execute_limit_orders(username, data, ex_rate):
    updated_orders = []
    executed_any = False
    for order in data.get("orders", []):
        tick = order["ticker"]
        target = order["target_price"]
        o_type = order["type"]
        qty = order["qty"]
        
        df, obj = load_stock_data(tick)
        curr_price = get_safe_current_price(obj, df)
        if curr_price == 0:
            updated_orders.append(order)
            continue
            
        is_ta_asset = ".TA" in tick
        curr_price_norm = curr_price / 100 if is_ta_asset else curr_price
        gross_cost_ils = qty * curr_price_norm * (1.0 if is_ta_asset else ex_rate)
        comm_ils = gross_cost_ils * COMMISSION_RATE
        
        if o_type == "BUY_LIMIT" and curr_price_norm <= target:
            if data["cash_ils"] >= (gross_cost_ils + comm_ils):
                data["cash_ils"] -= (gross_cost_ils + comm_ils)
                holding = data["portfolio"].get(tick, {"qty": 0, "avg_price_source": 0.0, "first_buy_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
                old_qty = holding["qty"]
                new_qty = old_qty + qty
                new_avg = ((old_qty * holding["avg_price_source"]) + (qty * curr_price_norm)) / new_qty if old_qty > 0 else curr_price_norm
                data["portfolio"][tick] = {"qty": new_qty, "avg_price_source": new_avg, "first_buy_time": holding.get("first_buy_time", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}
                add_to_history(username, tick, "BUY_LIMIT_EXEC", qty, curr_price_norm, (1.0 if is_ta_asset else ex_rate), comm_ils, 0.0, (gross_cost_ils + comm_ils))
                executed_any = True
            else: updated_orders.append(order)
        elif o_type == "SELL_LIMIT" and curr_price_norm >= target:
            holding = data["portfolio"].get(tick, {"qty": 0, "avg_price_source": 0.0})
            if holding["qty"] >= qty:
                profit = (curr_price_norm - holding["avg_price_source"]) * qty
                tax_ils = (profit * (1.0 if is_ta_asset else ex_rate) * TAX_RATE) if profit > 0 else 0.0
                total_rec_ils = gross_cost_ils - comm_ils - tax_ils
                data["cash_ils"] += total_rec_ils
                data["portfolio"][tick]["qty"] -= qty
                if data["portfolio"][tick]["qty"] == 0: del data["portfolio"][tick]
                add_to_history(username, tick, "SELL_LIMIT_EXEC", qty, curr_price_norm, (1.0 if is_ta_asset else ex_rate), comm_ils, tax_ils, total_rec_ils)
                executed_any = True
            else: pass
        else: updated_orders.append(order)
        
    if executed_any:
        data["orders"] = updated_orders
        save_user_data(username, data)
        return True
    return False

def calculate_achievements(data, total_net_worth):
    ach = {
        "צעד ראשון בשוק": {"desc": "ביצע עסקה ראשונה בסיมולטור", "unlocked": False},
        "המשקיע המגוון": {"desc": "מחזיק ב-3 מניות שונות במקביל", "unlocked": False},
        "מועדון ה-100K": {"desc": "שווי התיק חצה את רף ה-110,000 ש\"ח", "unlocked": False}
    }
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM history WHERE username=?", (st.session_state['logged_in_user'],))
    if c.fetchone()[0] > 0: ach["צעד ראשון בשוק"]["unlocked"] = True
    conn.close()
    if len(data["portfolio"]) >= 3: ach["המשקיע המגוון"]["unlocked"] = True
    if total_net_worth >= 110000.0: ach["מועדון ה-100K"]["unlocked"] = True
    return ach
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
    reasons.append("Bullish Trend (Above MA200)" if score > 0 else "Bearish Trend (Below MA200)")
    buy_threshold, sl_multiplier = (2, 0.98) if "Conservative" in selected_risk_profile else ((0, 0.94) if "Aggressive" in selected_risk_profile else (1, 0.96))
    verdict, v_type = ("Buy Opportunity", "BUY") if score >= buy_threshold else (("Wait for Drop", "WAIT") if score < 0 else ("Neutral / Hold", "HOLD"))
    return {"df": df, "verdict": verdict, "verdict_type": v_type, "current_price": current_price, "waiting_target": bb_lower_curr, "stop_loss_price": bb_lower_curr * sl_multiplier, "analysis_reasons": reasons}
# =========================================================
# חלק 4: ארכיטקטורת לשוניות וממשק התיק האישי והפילוח
# =========================================================
@st.fragment(run_every=60)
def render_realtime_simulator():
    global user_db, usd_ils, ticker_1
    
    if check_and_execute_limit_orders(current_user, user_db, usd_ils):
        user_db = load_user_data(current_user)
        
    portfolio_val_ils, holdings_dist = calculate_portfolio_value_ils(user_db["portfolio"], usd_ils)
    if pd.isna(portfolio_val_ils): portfolio_val_ils = 0.0
    total_net_worth_ils = user_db["cash_ils"] + portfolio_val_ils
    
    log_portfolio_history(current_user, total_net_worth_ils)
    achievements = calculate_achievements(user_db, total_net_worth_ils)
    
    tab_portfolio, tab_trade, tab_history, tab_ai = st.tabs([
        "Portfolio Summary", 
        "Trading Station", 
        "History & Watchlist",
        "AI Portfolio Advisor"
    ])
    
    with tab_portfolio:
        st.subheader("Account Net Worth & Summary")
        cw1, cw2, cw3 = st.columns(3)
        cw1.metric("Available Cash (ILS)", f"ILS {user_db['cash_ils']:,.2f}")
        cw2.metric("Stocks Value (ILS)", f"ILS {portfolio_val_ils:,.2f}")
        cw3.metric("Total Net Worth (ILS)", f"ILS {total_net_worth_ils:,.2f}")
        
        st.markdown("---")
        st.subheader("Open Positions")
        holding_rows = []
        pie_labels = ["Available Cash"]
        pie_values = [user_db["cash_ils"]]
        
        if user_db.get("portfolio"):
            for tick, info in user_db["portfolio"].items():
                qty = info.get("qty", 0)
                if qty <= 0: continue
                
                df, obj = load_stock_data(tick)
                price_raw = get_safe_current_price(obj, df)
                daily_chg = get_daily_change_pct(obj, df)
                is_ta_asset = ".TA" in tick
                
                if price_raw == 0:
                    price_raw = info.get("avg_price_source", 1.0)
                    if is_ta_asset: price_raw *= 100
                    
                curr_market_price = price_raw / 100 if is_ta_asset else price_raw
                asset_val_ils = curr_market_price * qty * (1.0 if is_ta_asset else usd_ils)
                currency_sym = "ILS " if is_ta_asset else "USD "
                
                pie_labels.append(tick)
                pie_values.append(asset_val_ils)
                
                avg_buy_cost = info.get("avg_price_source", 0.0)
                roi_pct = ((curr_market_price - avg_buy_cost) / avg_buy_cost) * 100 if avg_buy_cost > 0 else 0.0
                time_string = calculate_time_elapsed(info.get("first_buy_time", datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                
                holding_rows.append({
                    "Asset": tick,
                    "Shares": f"{qty:,.0f}",
                    "Avg Cost": f"{currency_sym}{avg_buy_cost:,.2f}",
                    "Market Price": f"{currency_sym}{curr_market_price:,.2f}",
                    "Total Value (ILS)": f"ILS {asset_val_ils:,.2f}",
                    "Daily Change": f"{daily_chg:+.2f}%",     
                    "Total Return (ROI)": f"{roi_pct:+.2f}%", 
                    "Holding Time": time_string
                })
                    
        if holding_rows:
            st.dataframe(pd.DataFrame(holding_rows).set_index("Asset"), use_container_width=True)
            
            g_col1, g_col2 = st.columns(2)
            with g_col1:
                st.subheader("Asset Allocation Chart")
                fig_pie = go.Figure(data=[go.Pie(labels=pie_labels, values=pie_values, hole=.4, textinfo='label+percent')])
                fig_pie.update_layout(template="plotly_dark", height=320, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig_pie, use_container_width=True)
            with g_col2:
                st.subheader("Performance Curve Over Time")
                hist_df = load_portfolio_history(current_user)
                if not hist_df.empty and len(hist_df) >= 2:
                    fig_line = go.Figure(data=[go.Scatter(x=hist_df['זמן'], y=hist_df['שווי תיק (₪)'], mode='lines+markers', line=dict(color='#00ffcc', width=2))])
                    fig_line.update_layout(template="plotly_dark", height=320, margin=dict(l=10, r=10, t=10, b=10))
                    st.plotly_chart(fig_line, use_container_width=True)
                else:
                    st.info("Performance curve will begin generating after multiple market fluctuations or trades.")
        else:
            st.info("Your portfolio is currently empty. Go to the Trading Station tab to invest.")
            
        st.markdown("---")
        st.subheader("Investor Achievements & Badges")
        ach_cols = st.columns(len(achievements))
        for idx, (title, details) in enumerate(achievements.items()):
            badge = "🏅" if details["unlocked"] else "🔒"
            status_color = "green" if details["unlocked"] else "gray"
            with ach_cols[idx]:
                st.markdown(f"<div style='text-align:center; padding:10px; border:1px solid {status_color}; border-radius:10px;'><h3>{badge}</h3><h4>{title}</h4><p style='font-size:11px; color:gray;'>{details['desc']}</p></div>", unsafe_allow_html=True)

    with tab_trade:
        if ticker_1:
            df1, stock_obj1 = load_stock_data(ticker_1)
            if not df1.empty and stock_obj1 and len(df1) > 20:
                is_ta = ".TA" in ticker_1
                res1 = analyze_ticker(df1, risk_profile, is_ta, stock_obj1)
                info = stock_obj1.info
                curr_price_normalized = res1['current_price']
                
                st.subheader(f"Order Placement Station: {ticker_1}")
                with st.expander("Company Business Summary & Fundamentals", expanded=True):
                    st.write(f"**Sector:** {info.get('sector', 'N/A')} | **Industry:** {info.get('industry', 'N/A')}")
                    st.write(f"**Summary:** {info.get('longBusinessSummary', 'No data available.')}")
                    returns_data = calculate_periodic_returns(ticker_1)
                    if returns_data: st.table(pd.DataFrame([returns_data]))

                tc1, tc2, tc3 = st.columns(3)
                holding_info = user_db["portfolio"].get(ticker_1, {"qty": 0, "avg_price_source": 0.0, "first_buy_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
                
                with tc1:
                    t_qty = st.number_input("Order Quantity (Units):", min_value=1, value=10, step=1, key="trade_qty_input")
                    action_mode = st.radio("Execution Type:", ["Market Price", "Limit Order Price"])
                    
                    target_price_limit = curr_price_normalized
                    if action_mode == "Limit Order Price":
                        target_price_limit = st.number_input("Target Limit Price:", min_value=0.01, value=curr_price_normalized, step=0.5)
                with tc2:
                    st.write(""); st.write("")
                    gross_cost_ils = t_qty * curr_price_normalized * (1.0 if is_ta else usd_ils)
                    commission_ils = gross_cost_ils * COMMISSION_RATE
                    
                    if st.button("🟢 Execute BUY Order", use_container_width=True, key="buy_btn"):
                        if action_mode == "Market Price":
                            total_charge_ils = gross_cost_ils + commission_ils
                            if user_db["cash_ils"] >= total_charge_ils:
                                user_db["cash_ils"] -= total_charge_ils
                                old_qty = holding_info["qty"]
                                old_avg = holding_info["avg_price_source"]
                                new_qty = old_qty + t_qty
                                weighted_avg_price = ((old_qty * old_avg) + (t_qty * curr_price_normalized)) / new_qty if old_qty > 0 else curr_price_normalized
                                b_time = holding_info.get("first_buy_time", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                                
                                user_db["portfolio"][ticker_1] = {"qty": new_qty, "avg_price_source": weighted_avg_price, "first_buy_time": b_time}
                                save_user_data(current_user, user_db)
                                add_to_history(current_user, ticker_1, "BUY", t_qty, curr_price_normalized, (1.0 if is_ta else usd_ils), commission_ils, 0.0, total_charge_ils)
                                st.success("Market BUY order executed successfully."); st.rerun()
                            else: st.error("Insufficient ILS cash.")
                        else:
                            user_db["orders"].append({
                                "ticker": ticker_1, "type": "BUY_LIMIT", "target_price": target_price_limit, 
                                "qty": t_qty, "date_placed": datetime.now().strftime('%m-%d %H:%M')
                            })
                            save_user_data(current_user, user_db)
                            st.info(f"Limit BUY order for {t_qty} units placed at {target_price_limit}."); st.rerun()
                            
                    if st.button("🔴 Execute SELL Order", use_container_width=True, key="sell_btn"):
                        if action_mode == "Market Price":
                            if holding_info["qty"] >= t_qty:
                                profit_source = (curr_price_normalized - holding_info["avg_price_source"]) * t_qty
                                tax_ils = (profit_source * (1.0 if is_ta else usd_ils) * TAX_RATE) if profit_source > 0 else 0.0
                                total_receive_ils = gross_cost_ils - commission_ils - tax_ils
                                
                                user_db["cash_ils"] += total_receive_ils
                                user_db["portfolio"][ticker_1]["qty"] -= t_qty
                                if user_db["portfolio"][ticker_1]["qty"] == 0: del user_db["portfolio"][ticker_1]
                                save_user_data(current_user, user_db)
                                add_to_history(current_user, ticker_1, "SELL", t_qty, curr_price_normalized, (1.0 if is_ta else usd_ils), commission_ils, tax_ils, total_receive_ils)
                                st.success("Market SELL order executed successfully."); st.rerun()
                            else: st.error("Not enough shares to sell.")
                        else:
                            if holding_info["qty"] >= t_qty:
                                user_db["orders"].append({
                                    "ticker": ticker_1, "type": "SELL_LIMIT", "target_price": target_price_limit, 
                                    "qty": t_qty, "date_placed": datetime.now().strftime('%m-%d %H:%M')
                                })
                                save_user_data(current_user, user_db)
                                st.info(f"Limit SELL order for {t_qty} units placed at {target_price_limit}."); st.rerun()
                            else: st.error("Insufficient shares to place a limit sell order.")

                with tc3:
                    symbol_lbl = "₪" if is_ta else "$"
                    st.info(f"Shares Held: **{holding_info['qty']}**\n\nMarket Price: **{symbol_lbl}{curr_price_normalized:,.2f}**")

                st.markdown("---")
                st.subheader("📊 Technical Metrics & System Verdict")
                st.metric("System Recommendation", res1['verdict'])
                
                df = res1['df']
                fig = make_subplots(rows=1, cols=1)
                fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close']))
                fig.update_layout(xaxis_rangeslider_visible=False, template="plotly_dark", height=320, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.error("Please enter a valid stock ticker in the sidebar.")

    # -----------------------------------------------------
    # לשונית 3: היסטוריית פעולות, פקודות ממתינות ורשימת מעקב
    # -----------------------------------------------------
    with tab_history:
        st.subheader("⭐ Personal Watchlist")
        if ticker_1 and st.button("➕/➖ Toggle Watchlist Status"):
            if ticker_1 not in user_db["watchlist"]: 
                user_db["watchlist"].append(ticker_1)
            else: 
                user_db["watchlist"].remove(ticker_1)
            save_user_data(current_user, user_db)
            st.rerun()
            
        if user_db["watchlist"]: 
            st.write(user_db["watchlist"])
        
        st.markdown("---")
        st.subheader("⏳ Pending Limit Orders")
        if user_db.get("orders"):
            st.dataframe(pd.DataFrame(user_db["orders"]), use_container_width=True)
        else: 
            st.info("No pending limit orders at this time.")
        
        st.markdown("---")
        st.subheader("📜 Transaction Log")
        hist_df = load_user_history(current_user)
        if not hist_df.empty: 
            st.dataframe(hist_df, use_container_width=True)
        else: 
            st.info("No recorded actions for this account yet.")

    # -----------------------------------------------------
    # לשונית 4: יועץ השקעות אוטומטי מבוסס AI Advisor
    # -----------------------------------------------------
    with tab_ai:
        st.subheader("🧠 AI Portfolio Advisor")
        st.write("The artificial intelligence engine analyzes your allocations and risks to provide guidance:")
        
        ai_recommendations = []
        tech_count = sum(1 for t in user_db["portfolio"].keys() if t in ["AAPL", "MSFT", "NVDA", "NICE.TA"])
        
        if portfolio_val_ils == 0:
            ai_recommendations.append("💼 **All Cash Portfolio:** Your account currently holds 100% cash. We recommend making your first simulation trade to build confidence.")
        else:
            cash_pct = (user_db["cash_ils"] / total_net_worth_ils) * 100
            if cash_pct > 70:
                ai_recommendations.append("💵 **High Liquidity:** You hold over 70% in cash. Consider capitalizing on buying opportunities when stocks hit lower bands.")
            if tech_count >= 2:
                ai_recommendations.append("⚠️ **Tech Concentration Risk:** We detected a high cluster of technology assets. Diversifying into Healthcare or Financial sectors could mitigate risk.")
                
        if len(user_db["portfolio"]) >= 3:
            ai_recommendations.append("🛡️ **Excellent Diversification:** Good job! Splitting your positions across multiple assets lowers your overall risk volatility.")
            
        for rec in ai_recommendations:
            st.info(rec)

render_realtime_simulator()
