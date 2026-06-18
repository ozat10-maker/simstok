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
# חלק 1: הגדרות דף, בסיס נתונים SQLite יציב (גרסה 15) ומיסוי
# =========================================================
st.set_page_config(page_title="סימולטור השקעות מקצועי", layout="wide")

DB_FILE = "/tmp/simulator_pro_v15.db" 
TAX_RATE = 0.25      
COMMISSION_RATE = 0.001 

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # טבלת משתמשים
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, cash_ils REAL, portfolio TEXT, orders TEXT, watchlist TEXT)''')
    # טבלת היסטוריית פעולות
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, timestamp TEXT, ticker TEXT, 
                  action TEXT, qty REAL, price_usd REAL, ex_rate REAL, commission_ils REAL, tax_ils REAL, total_ils REAL)''')
    # טבלת היסטוריית שווי התיק לצורך גרף קווי לאורך זמן
    c.execute('''CREATE TABLE IF NOT EXISTS portfolio_history 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, timestamp TEXT, net_worth REAL)''')
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
    df = pd.read_sql_query("SELECT timestamp as 'זמן', ticker as 'נכס', action as 'פעולה', qty as 'כמות', price_usd as 'מחיר מקור', ex_rate as 'שער המרה', commission_ils as 'עמלה (שח)', tax_ils as 'מס (שח)', total_ils as 'סך הכל (שח)' FROM history WHERE username=? ORDER BY id DESC", conn, params=(username,))
    conn.close()
    return df

def log_portfolio_history(username, net_worth):
    """תיעוד שווי התיק לצורך גרף קווי של ביצועים לאורך זמן"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("SELECT net_worth FROM portfolio_history WHERE username=? ORDER BY id DESC LIMIT 1", (username,))
    last_row = c.fetchone()
    if last_row is None or abs(last_row[0] - net_worth) > 10.0:
        c.execute("INSERT INTO portfolio_history (username, timestamp, net_worth) VALUES (?, ?, ?)", (username, now_str, net_worth))
        conn.commit()
    conn.close()

def load_portfolio_history(username):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT timestamp as 'זמן', net_worth as 'שווי תיק (₪)' FROM portfolio_history WHERE username=? ORDER BY id ASC", conn, params=(username,))
    conn.close()
    return df

def get_usd_ils_rate():
    try:
        df = yf.Ticker("USDILS=X").history(period="1d")
        if not df.empty and pd.notna(df['Close'].iloc[-1]):
            return float(df['Close'].iloc[-1])
        return 3.70
    except: return 3.70

def render_top_market_indices():
    indices = {"S&P 500": "^GSPC", "Nasdaq 100": "^NDX", "מדד ת\"א 125": "^TA125.TA", "Bitcoin": "BTC-USD"}
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
            cols[i].metric(name, f"${close_today:,.2f}" if "$" in name or "Bitcoin" in name else f"₪{close_today:,.2f}", f"{pct_change:+.2f}%")
        except: cols[i].metric(name, "טוען...")

init_db()
st.title("📈 פלטפורמת מסחר וסימולציה מתקדמת")
render_top_market_indices()
st.markdown("---")

if 'logged_in_user' not in st.session_state:
    st.session_state['logged_in_user'] = None

if st.session_state['logged_in_user'] is None:
    st.subheader("🔐 התחברות מאובטחת לניהול תיק אישי")
    auth_tab1, auth_tab2 = st.tabs(["🔑 התחברות משתמש", "📝 פתיחת חשבון חדש"])
    with auth_tab1:
        login_user_input = st.text_input("שם משתמש:", key="login_user").strip()
        login_pass_input = st.text_input("סיסמה:", type="password", key="login_pass").strip()
        if st.button("התחבר למערכת", use_container_width=True):
            if login_user_input and login_pass_input and login_user(login_user_input, login_pass_input):
                st.session_state['logged_in_user'] = login_user_input
                st.success("תיק ההשקעות נטען בהצלחה.")
                st.rerun()
            else: st.error("שם משתמש או סיסמה שגויים.")
    with auth_tab2:
        reg_user_input = st.text_input("בחר שם משתמש:", key="reg_user").strip()
        reg_pass_input = st.text_input("בחר סיסמה:", type="password", key="reg_pass").strip()
        if st.button("צור חשבון סימולציה חדש", use_container_width=True):
            if reg_user_input and reg_pass_input:
                if register_user(reg_user_input, reg_pass_input): st.success("החשבון נוצר! בצע התחברות כעת.")
                else: st.error("שם המשתמש תפוס.")
    st.stop()

current_user = st.session_state['logged_in_user']
user_db = load_user_data(current_user)
usd_ils = get_usd_ils_rate()

st.sidebar.subheader(f"👤 משקיע: {current_user}")
st.sidebar.info(f"💵 שער חליפין: 1$ = ₪{usd_ils:.3f}")
if st.sidebar.button("🚪 התנתק בבטחה"):
    st.session_state['logged_in_user'] = None
    st.rerun()
st.sidebar.markdown("---")

risk_profile = st.sidebar.selectbox(":פרופיל משקיע", ["(Aggressive (אגרסיבי", "(Moderate (מאוזן ", "(Conservative (סולידי"], index=1)
is_israeli = st.sidebar.checkbox("🇮🇱 מניה מהבורסה בתל אביב (TASE)")
raw_ticker = st.sidebar.text_input("הזן סימול או מספר נייר:", value="AAPL").upper().strip()

ticker_1 = f"{raw_ticker}.TA" if is_israeli and not raw_ticker.endswith(".TA") else raw_ticker
end_date = datetime.today()
start_date = end_date - timedelta(days=365 * 2)
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
    ma200_curr = df['MA200'].iloc[-1] if pd.notna(df['MA200'].iloc[-1]) else current_price
    bb_lower_curr = df['BB_Lower'].iloc[-1] if pd.notna(df['BB_Lower'].iloc[-1]) else current_price * 0.95
    if is_ils_stock:
        current_price /= 100
        ma200_curr /= 100
        bb_lower_curr /= 100
    reasons = []
    score = 1 if current_price > ma200_curr else -1
    reasons.append(f"המניה במגמה חיובית." if score > 0 else f"המניה בתיקון טכני.")
    buy_threshold, sl_multiplier = (2, 0.98) if "סולידי" in selected_risk_profile else ((0, 0.94) if "אגרסיבי" in selected_risk_profile else (1, 0.96))
    verdict, v_type = ("הזדמנות קנייה (Buy)", "BUY") if score >= buy_threshold else (("להמתין לירידה (Wait)", "WAIT") if score < 0 else ("החזק / ניטרלי (Hold)", "HOLD"))
    return {"df": df, "verdict": verdict, "verdict_type": v_type, "current_price": current_price, "waiting_target": bb_lower_curr, "stop_loss_price": bb_lower_curr * sl_multiplier, "analysis_reasons": reasons}
def check_and_execute_limit_orders(username, data, ex_rate):
    """מנוע בדיקה וביצוע אוטומטי של פקודות עתידיות (Limit Orders)"""
    updated_orders = []
    executed_any = False
    for order in data.get("orders", []):
        tick, target, o_type, qty = order["ticker"], order["target_price"], order["type"], order["qty"]
        df, obj = load_stock_data(tick)
        price_raw = get_safe_current_price(obj, df)
        if price_raw == 0:
            updated_orders.append(order)
            continue
        is_ta = ".TA" in tick
        curr_m_price = price_raw / 100 if is_ta else price_raw
        
        # תנאי הפעלה לקנייה או מכירה עתידית
        if o_type == "BUY_LIMIT" and curr_m_price <= target:
            gross_ils = qty * curr_m_price * (1.0 if is_ta else ex_rate)
            comm_ils = gross_ils * COMMISSION_RATE
            if data["cash_ils"] >= (gross_ils + comm_ils):
                data["cash_ils"] -= (gross_ils + comm_ils)
                holding = data["portfolio"].get(tick, {"qty": 0, "avg_price_source": 0.0, "first_buy_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
                new_qty = holding["qty"] + qty
                new_avg = ((holding["qty"] * holding["avg_price_source"]) + (qty * curr_m_price)) / new_qty
                b_time = holding.get("first_buy_time", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                data["portfolio"][tick] = {"qty": new_qty, "avg_price_source": new_avg, "first_buy_time": b_time}
                add_to_history(username, tick, "BUY_LIMIT", qty, curr_m_price, (1.0 if is_ta else ex_rate), comm_ils, 0.0, (gross_ils + comm_ils))
                executed_any = True
            else: updated_orders.append(order)
        elif o_type == "SELL_LIMIT" and curr_m_price >= target:
            holding = data["portfolio"].get(tick, {"qty": 0, "avg_price_source": 0.0})
            if holding["qty"] >= qty:
                gross_ils = qty * curr_m_price * (1.0 if is_ta else ex_rate)
                comm_ils = gross_ils * COMMISSION_RATE
                profit = (curr_m_price - holding["avg_price_source"]) * qty
                tax_ils = (profit * (1.0 if is_ta else ex_rate) * TAX_RATE) if profit > 0 else 0.0
                data["cash_ils"] += (gross_ils - comm_ils - tax_ils)
                data["portfolio"][tick]["qty"] -= qty
                if data["portfolio"][tick]["qty"] == 0: del data["portfolio"][tick]
                add_to_history(username, tick, "SELL_LIMIT", qty, curr_m_price, (1.0 if is_ta else ex_rate), comm_ils, tax_ils, (gross_ils - comm_ils - tax_ils))
                executed_any = True
            else: pass
        else: updated_orders.append(order)
    if executed_any:
        data["orders"] = updated_orders
        save_user_data(username, data)
        return True
    return False

def calculate_achievements(data, net_worth):
    """מערכת הישגים, גביעים ומשימות למשתמש"""
    hist_count = len(data["portfolio"])
    ach = {
        "משקיע מתחיל": {"desc": "ביצוע פוזיציית קנייה ראשונה בסימולטור", "unlocked": hist_count > 0},
        "המשקיע המגוון": {"desc": "פיזור תיק ההשקעות ב-3 מניות שונות לפחות", "unlocked": hist_count >= 3},
        "מועדון ה-100K": {"desc": "השגת שווי תיק כולל של מעל 105,000 ש\"ח", "unlocked": net_worth >= 105000}
    }
    return ach
            with tc3:
                symbol_lbl = "₪" if is_ta else "$"
                st.info(f"ברשותך כרגע **{holding_info['qty']}** מניות.\n\nמחיר שוק: **{symbol_lbl}{curr_price_normalized:,.2f}**")

            st.markdown("---")
            st.subheader("📊 המלצות מערכת ומפת מגמות")
            st.metric("החלטת מנוע", res1['verdict'])
            
            df = res1['df']
            fig = make_subplots(rows=1, cols=1)
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close']))
            fig.update_layout(xaxis_rangeslider_visible=False, template="plotly_dark", height=320, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.error("הזן סימול מניה תקין בסרגל הצדי כדי להציג את חדר המסחר.")

    # -----------------------------------------------------
    # לשונית 3: היסטוריית פעולות, פקודות ממתינות ורשימת מעקב
    # -----------------------------------------------------
    with tab_history:
        st.subheader("⭐ מניות במעקב (Watchlist)")
        if ticker_1 and st.button("➕/➖ שנה סטטוס מעקב עבור המניה הנוכחית"):
            if ticker_1 not in user_db["watchlist"]: 
                user_db["watchlist"].append(ticker_1)
            else: 
                user_db["watchlist"].remove(ticker_1)
            save_user_data(current_user, user_db)
            st.rerun()
            
        if user_db["watchlist"]: 
            st.write(user_db["watchlist"])
        
        st.markdown("---")
        st.subheader("⏳ פקודות עתידיות ממתינות לביצוע (Limit Orders)")
        if user_db.get("orders"):
            st.dataframe(pd.DataFrame(user_db["orders"]), use_container_width=True)
        else: 
            st.info("אין פקודות עתידיות ממתינות בחשבונך כרגע.")
        
        st.markdown("---")
        st.subheader("📜 יומן עסקאות מלא")
        hist_df = load_user_history(current_user)
        if not hist_df.empty: 
            st.dataframe(hist_df, use_container_width=True)
        else: 
            st.info("לא בוצעו פעולות בחשבון זה.")

    # -----------------------------------------------------
    # לשונית 4: יועץ השקעות אוטומטי מבוסס AI Advisor
    # -----------------------------------------------------
    with tab_ai:
        st.subheader("🧠 יועץ השקעות וירטואלי - ניתוח ואופטימיזציה")
        st.write("מנוע הבינה המלאכותית סורק את פיזור הנכסים, המיסים והביצועים שלך ומספק תובנות פעולה:")
        
        ai_recommendations = []
        tech_count = sum(1 for t in user_db["portfolio"].keys() if t in ["AAPL", "MSFT", "NVDA", "NICE.TA"])
        
        if portfolio_val_ils == 0:
            ai_recommendations.append("💼 **תיק במזומן מלא:** התיק שלך מורכב כרגע מ-100% מזומן. מומלץ לבצע עסקת סימולציה ראשונה כדי לצבור ביטחון.")
        else:
            cash_pct = (user_db["cash_ils"] / total_net_worth_ils) * 100
            if cash_pct > 70:
                ai_recommendations.append("💵 **נזילות גבוהה מדי:** יש לך מעל 70% מזומן פנוי. שקול לנצל הזדמנויות קנייה (Buy) במניות המציגות קרבה לרצועת בולינגר התחתונה.")
            if tech_count >= 2:
                ai_recommendations.append("⚠️ **חשיפת יתר לטכנולוגיה:** זיהינו ריכוז גבוה של נכסי טכנולוגיה בתיק. מומלץ לגוון ולרכוש מניות מסקטורים אחרים.")
                
        if len(user_db["portfolio"]) >= 3:
            ai_recommendations.append("🛡️ **פיזור מעולה:** כל הכבוד! פיזרת את הפוזיציות שלך על פני מספר נכסים שונים, מה שמקטין את הסיכון.")
            
        for rec in ai_recommendations:
            st.info(rec)

render_realtime_simulator()
