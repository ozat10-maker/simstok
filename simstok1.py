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
# חלק 1: הגדרות דף, בסיס נתונים SQLite משודרג למיסים והיסטוריה
# =========================================================
st.set_page_config(page_title="סימולטור השקעות מקצועי", layout="wide")

DB_FILE = "simulator_pro_users.db"
TAX_RATE = 0.25      # 25% מס רווח הון
COMMISSION_RATE = 0.001 # 0.1% עמלת מסחר ממוצעת בשוק

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # טבלת משתמשים (כולל רשימת מעקב ומחיר קנייה ממוצע בפורמט JSON)
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, cash_ils REAL, portfolio TEXT, orders TEXT, watchlist TEXT)''')
    # טבלת היסטוריית פעולות מפורטת
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
    # משתמש חדש מתחיל עם 100,000 ש"ח פנויים למסחר
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
        return {"cash_ils": row[0], "portfolio": json.loads(row[1]), "orders": json.loads(row[2]), "watchlist": json.loads(row[3])}
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
    df = pd.read_sql_query("SELECT timestamp as 'זמן', ticker as 'נכס', action as 'פעולה', qty as 'כמות', price_usd as 'מחיר ($)', ex_rate as 'שער המרה', commission_ils as 'עמלה (שח)', tax_ils as 'מס שולם (שח)', total_ils as 'סך הכל (שח)' FROM history WHERE username=? ORDER BY id DESC", conn, params=(username,))
    conn.close()
    return df

init_db()

def get_usd_ils_rate():
    """משיכת שער חליפין דולר-שקל עדכני מהשוק"""
    try:
        df = yf.Ticker("USDILS=X").history(period="1d")
        return float(df['Close'].iloc[-1]) if not df.empty else 3.70
    except:
        return 3.70

def render_top_market_indices():
    indices = {"S&P 500": "^GSPC", "Nasdaq 100": "^NDX", "דלתא דולר/שקל": "USDILS=X", "Bitcoin": "BTC-USD"}
    cols = st.columns(len(indices))
    for i, (name, ticker) in enumerate(indices.items()):
        try:
            df = yf.Ticker(ticker).history(period="2d")
            if len(df) >= 2:
                close_today = df['Close'].iloc[-1]
                close_yesterday = df['Close'].iloc[-2]
                pct_change = ((close_today - close_yesterday) / close_yesterday) * 100
                cols[i].metric(name, f"${close_today:,.2f}" if "ILS" not in ticker else f"₪{close_today:.3f}", f"{pct_change:+.2f}%")
            else: cols[i].metric(name, "טוען...")
        except: cols[i].metric(name, "שגיאה")

st.title("📈 סימולטור מסחר מקצועי כולל מיסוי, עמלות והמרת מטח")
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
                st.success(f"שלום {login_user_input}, תיק ההשקעות נטען בהצלחה.")
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
st.sidebar.info(f"💵 שער חליפין עדכני: 1$ = ₪{usd_ils:.3f}")
if st.sidebar.button("🚪 התנתק בבטחה"):
    st.session_state['logged_in_user'] = None
    st.rerun()
st.sidebar.markdown("---")

risk_profile = st.sidebar.selectbox(":פרופיל משקיע", ["(Aggressive (אגרסיבי", "(Moderate (מאוזן ", "(Conservative (סולידי"], index=1)
ticker_1 = st.sidebar.text_input("🔍 הזן סימול מניה (למשל: TSLA, NVDA)", value="AAPL").upper().strip()
def load_stock_data(ticker_symbol):
    if not ticker_symbol: return pd.DataFrame(), None
    try:
        stock_obj = yf.Ticker(ticker_symbol)
        return stock_obj.history(start=datetime.today() - timedelta(days=365), end=datetime.today(), auto_adjust=True), stock_obj
    except: return pd.DataFrame(), None

def calculate_periodic_returns(ticker_symbol):
    try:
        stock = yf.Ticker(ticker_symbol)
        df = stock.history(period="1y")
        if df.empty or len(df) < 5: return None
        curr = df['Close'].iloc[-1]
        def get_pct(days):
            old = df['Close'].iloc[max(0, len(df) - days)]
            return ((curr - old) / old) * 100
        return {"שבוע": f"{get_pct(5):+.2f}%", "חודש": f"{get_pct(21):+.2f}%", "חצי שנה": f"{get_pct(126):+.2f}%", "שנה": f"{get_pct(len(df)-1):+.2f}%"}
    except: return None

def get_sector_leaderboard(sector_name):
    sector_map = {
        "טכנולוגיה (Technology)": ["AAPL", "MSFT", "NVDA", "GOOGL"],
        "בריאות (Healthcare)": ["JNJ", "LLY", "PFE", "UNH"],
        "אנרגיה (Energy)": ["XOM", "CVX", "COP", "SLB"]
    }
    tickers = sector_map.get(sector_name, ["AAPL", "MSFT"])
    rows = []
    for tick in tickers:
        try:
            df = yf.Ticker(tick).history(period="2d")
            if not df.empty and len(df) >= 2:
                c_p = df['Close'].iloc[-1]
                y_p = df['Close'].iloc[-2]
                chg = ((c_p - y_p) / y_p) * 100
                rows.append({"סימול": tick, "מחיר": f"${c_p:,.2f}", "שינוי יומי": f"{chg:+.2f}%", "raw": chg})
        except: pass
    return rows

def calculate_portfolio_value_ils(portfolio, ex_rate):
    total_val_ils = 0.0
    shares_data = {}
    for tick, info in portfolio.items():
        qty = info.get("qty", 0)
        if qty <= 0: continue
        df, _ = load_stock_data(tick)
        if not df.empty:
            price_usd = float(df['Close'].iloc[-1])
            val_ils = price_usd * qty * ex_rate
            total_val_ils += val_ils
            shares_data[tick] = {"val_ils": val_ils, "price_usd": price_usd}
    return total_val_ils, shares_data
# =========================================================
# חלק 4: ממשק משתמש, רשימת מעקב, דוחות מס והיסטוריה
# =========================================================
@st.fragment(run_every=60)
def render_realtime_simulator():
    global user_db, usd_ils
    
    portfolio_val_ils, holdings_dist = calculate_portfolio_value_ils(user_db["portfolio"], usd_ils)
    total_net_worth_ils = user_db["cash_ils"] + portfolio_val_ils
    
    # מניות מובילות במשק
    st.subheader("🏆 המניות החזקות ביותר בשוק")
    sec_choice = st.selectbox("בחר סקטור מוביל:", ["טכנולוגיה (Technology)", "בריאות (Healthcare)", "אנרגיה (Energy)"])
    leaders = get_sector_leaderboard(sec_choice)
    if leaders:
        st.dataframe(pd.DataFrame(leaders).sort_values(by="raw", ascending=False)[["סימול", "מחיר", "שינוי יומי"]], use_container_width=True)
        
    # רשימת מעקב אישית (Watchlist)
    st.subheader("⭐ רשימת המעקב האישית שלי")
    if user_db["watchlist"]:
        wl_data = []
        for w_tick in user_db["watchlist"]:
            df, _ = load_stock_data(w_tick)
            if not df.empty:
                wl_data.append({"סימול": w_tick, "מחיר שוק": f"${df['Close'].iloc[-1]:,.2f}", "נפח מסחר": f"{df['Volume'].iloc[-1]:,.0f}"})
        st.table(pd.DataFrame(wl_data))
    else: st.info("רשימת המעקב שלך ריקה כרגע.")

    # מצב חשבון בשקלים
    st.subheader(f"💼 חדר מסחר מקצועי (חשבון בשקלים) - משתמש: {current_user}")
    cw1, cw2, cw3 = st.columns(3)
    cw1.metric("💵 יתרת מזומן פנויה (ILS)", f"₪{user_db['cash_ils']:,.2f}")
    cw2.metric("📦 שווי החזקות במניות (ILS)", f"₪{portfolio_val_ils:,.2f}")
    cw3.metric("👑 שווי תיק כולל (Net Worth)", f"₪{total_net_worth_ils:,.2f}")

    if ticker_1:
        df1, stock_obj1 = load_stock_data(ticker_1)
        if not df1.empty and stock_obj1:
            curr_usd = float(df1['Close'].iloc[-1])
            
            # ניהול כפתור רשימת מעקב
            if ticker_1 not in user_db["watchlist"]:
                if st.button(f"➕ הוסף את {ticker_1} לרשימת המעקב", use_container_width=False):
                    user_db["watchlist"].append(ticker_1)
                    save_user_data(current_user, user_db); st.rerun()
            else:
                if st.button(f"➖ הסר את {ticker_1} מרשימת המעקב", use_container_width=False):
                    user_db["watchlist"].remove(ticker_1)
                    save_user_data(current_user, user_db); st.rerun()

            st.subheader(f"🎛️ ביצוע הוראת מסחר עבור: {ticker_1}")
            t_qty = st.number_input("כמות יחידות לביצוע:", min_value=1, value=10, step=1)
            
            # --- חישוב פרמטרים ודוח פעולה משוער ---
            gross_cost_ils = t_qty * curr_usd * usd_ils
            commission_ils = gross_cost_ils * COMMISSION_RATE
            
            st.markdown("### 📋 דוח פעולה ורישום פוזיציה משוער")
            rep_c1, rep_c2, rep_c3 = st.columns(3)
            rep_c1.write(f"**שווי נכס ברוטו:** ₪{gross_cost_ils:,.2f} (${curr_usd * t_qty:,.2f})")
            rep_c2.write(f"**עמלת מסחר שוק (0.1%):** ₪{commission_ils:,.2f}")
            
            holding_info = user_db["portfolio"].get(ticker_1, {"qty": 0, "avg_price_usd": 0.0})
            est_tax_ils = 0.0
            if holding_info["qty"] > 0:
                profit_per_share_usd = curr_usd - holding_info["avg_price_usd"]
                if profit_per_share_usd > 0:
                    est_tax_ils = (profit_per_share_usd * t_qty * usd_ils) * TAX_RATE
            rep_c3.write(f"**מס רווח הון משוער (25%):** ₪{est_tax_ils:,.2f}")

            act_c1, act_c2 = st.columns(2)
            if act_c1.button("🟢 בצע פקודת קנייה", use_container_width=True):
                total_charge_ils = gross_cost_ils + commission_ils
                if user_db["cash_ils"] >= total_charge_ils:
                    user_db["cash_ils"] -= total_charge_ils
                    new_qty = holding_info["qty"] + t_qty
                    new_avg = ((holding_info["qty"] * holding_info["avg_price_usd"]) + (t_qty * curr_usd)) / new_qty
                    user_db["portfolio"][ticker_1] = {"qty": new_qty, "avg_price_usd": new_avg}
                    save_user_data(current_user, user_db)
                    add_to_history(current_user, ticker_1, "BUY", t_qty, curr_usd, usd_ils, commission_ils, 0.0, total_charge_ils)
                    st.success("הקנייה בוצעה ונרשמה בהיסטוריה."); st.rerun()
                else: st.error("אין מספיק שקלים בארנק.")

            if act_c2.button("🔴 בצע פקודת מכירה", use_container_width=True):
                if holding_info["qty"] >= t_qty:
                    profit_usd = (curr_usd - holding_info["avg_price_usd"]) * t_qty
                    tax_ils = (profit_usd * usd_ils * TAX_RATE) if profit_usd > 0 else 0.0
                    total_receive_ils = gross_cost_ils - commission_ils - tax_ils
                    
                    user_db["cash_ils"] += total_receive_ils
                    user_db["portfolio"][ticker_1]["qty"] -= t_qty
                    if user_db["portfolio"][ticker_1]["qty"] == 0: del user_db["portfolio"][ticker_1]
                    save_user_data(current_user, user_db)
                    add_to_history(current_user, ticker_1, "SELL", t_qty, curr_usd, usd_ils, commission_ils, tax_ils, total_receive_ils)
                    st.success("המכירה בוצעה, המס נוכה והפעולה נרשמה בהיסטוריה."); st.rerun()
                else: st.error("אין לך מספיק מניות למכירה.")

    # תצוגת היסטוריית פעולות מלאה של המשתמש
    st.markdown("---")
    st.subheader("📜 יומן פעולות והיסטוריית עסקאות מלאה")
    hist_df = load_user_history(current_user)
    if not hist_df.empty: st.dataframe(hist_df, use_container_width=True)
    else: st.info("לא בוצעו עסקאות בחשבון זה עדיין.")

render_realtime_simulator()
