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
# חלק 1: הגדרות דף, בסיס נתונים SQLite משודרג (גרסה 9) ומיסוי
# =========================================================
st.set_page_config(page_title="סימולטור השקעות מקצועי", layout="wide")

DB_FILE = "/tmp/simulator_pro_v9.db" # עדכון גרסה לתמיכה בשכלול ממוצעים נקי
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
            "cash_ils": float(row) if pd.notna(row) else 100000.0, 
            "portfolio": json.loads(row) if row else {}, 
            "orders": json.loads(row) if row else [], 
            "watchlist": json.loads(row) if row else []
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
    df = pd.read_sql_query("SELECT timestamp as 'זמן', ticker as 'נכס', action as 'פעולה', qty as 'כמות', price_usd as 'מחיר מטבע מקור', ex_rate as 'שער המרה (לשקל)', commission_ils as 'עמלה (שח)', tax_ils as 'מס שולם (שח)', total_ils as 'סך הכל (שח)' FROM history WHERE username=? ORDER BY id DESC", conn, params=(username,))
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
                
            if close_yesterday > 0:
                pct_change = ((close_today - close_yesterday) / close_yesterday) * 100
            else: pct_change = 0.0
            
            cols[i].metric(name, f"${close_today:,.2f}" if "$" in name or "Bitcoin" in name else f"₪{close_today:,.2f}", f"{pct_change:+.2f}%")
        except: 
            cols[i].metric(name, "טוען...")

st.title("📈 סימולטור מסחר מקצועי - מנוע משולב")
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
            else: st.error("שם משתמש או סיסמה שגויים. נסה להירשם מחדש במידת הצורך.")
    with auth_tab2:
        reg_user_input = st.text_input("בחר שם משתמש:", key="reg_user").strip()
        reg_pass_input = st.text_input("בחר סיסמה:", type="password", key="reg_pass").strip()
        if st.button("צור חשבון סימולציה חדש", use_container_width=True):
            if reg_user_input and reg_pass_input:
                if register_user(reg_user_input, reg_pass_input): st.success("החשבון נוצר! בצע התחברות כעת.")
                else: st.error("שם המשתמש תפוס.")
            else: st.warning("אנא מלא את כל השדות.")
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
st.sidebar.write("**🔍 חיפוש נייר ערך למסחר**")
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
    """מנגנון אבטחה קריטי לשליפת מחיר השוק וניקוי nan"""
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
    """חישוב אחוז השינוי היומי (התנועה של המניה היום בשוק) עבור טבלת התיק"""
    try:
        if df is not None and len(df) >= 2:
            c_p = df['Close'].iloc[-1]
            y_p = df['Close'].iloc[-2]
            if y_p > 0:
                return ((c_p - y_p) / y_p) * 100
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
    df['BB_Lower'] = df['BB_Middle'] - (2 * df['BB_Std'])
    current_price = get_safe_current_price(stock_obj, df)
    ma200_curr = df['MA200'].iloc[-1] if pd.notna(df['MA200'].iloc[-1]) else current_price
    bb_lower_curr = df['BB_Lower'].iloc[-1] if pd.notna(df['BB_Lower'].iloc[-1]) else current_price * 0.95
    if is_ils_stock:
        current_price /= 100
        ma200_curr /= 100
        bb_lower_curr /= 100
    reasons = []
    score = 1 if current_price > ma200_curr else -1
    reasons.append(f"המניה במגמה ראשית עולה." if score > 0 else f"המניה במגמת תיקון טכני.")
    buy_threshold, sl_multiplier = (2, 0.98) if "סולידי" in selected_risk_profile else ((0, 0.94) if "אגרסיבי" in selected_risk_profile else (1, 0.96))
    verdict, v_type = ("הזדמנות קנייה (Buy)", "BUY") if score >= buy_threshold else (("להמתין לירידה (Wait)", "WAIT") if score < 0 else ("החזק / ניטרלי (Hold)", "HOLD"))
    return {"df": df, "verdict": verdict, "verdict_type": v_type, "current_price": current_price, "waiting_target": bb_lower_curr, "stop_loss_price": bb_lower_curr * sl_multiplier, "analysis_reasons": reasons}
# =========================================================
# חלק 4: ממשק משתמש, שכלול ממוצעי קנייה ותצוגת התיק המשופר
# =========================================================
@st.fragment(run_every=60)
def render_realtime_simulator():
    global user_db, usd_ils, ticker_1
    
    portfolio_val_ils, holdings_dist = calculate_portfolio_value_ils(user_db["portfolio"], usd_ils)
    if pd.isna(portfolio_val_ils): portfolio_val_ils = 0.0
    total_net_worth_ils = user_db["cash_ils"] + portfolio_val_ils
    
    # --- תצוגת טבלת תיק המסחר המשודרגת (כולל תשואה כוללת ושינוי יומי) ---
    st.subheader("💼 תיק ההשקעות ומצבת פוזיציות פתוחות")
    holding_rows = []
    
    if user_db.get("portfolio"):
        for tick, info in user_db["portfolio"].items():
            qty = info.get("qty", 0)
            if qty <= 0: continue
            
            df, obj = load_stock_data(tick)
            price_raw = get_safe_current_price(obj, df)
            daily_chg = get_daily_change_pct(obj, df) # שליפת אחוז תנועת המניה היום
            is_ta_asset = ".TA" in tick
            
            if price_raw == 0:
                price_raw = info.get("avg_price_source", 1.0)
                if is_ta_asset: price_raw *= 100
                
            curr_market_price = price_raw / 100 if is_ta_asset else price_raw
            currency_sym = "₪" if is_ta_asset else "$"
            
            avg_buy_cost = info.get("avg_price_source", 0.0)
            roi_pct = ((curr_market_price - avg_buy_cost) / avg_buy_cost) * 100 if avg_buy_cost > 0 else 0.0
            time_string = calculate_time_elapsed(info.get("first_buy_time", datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            
            holding_rows.append({
                "סימול מניה": tick,
                "כמות יחידות": f"{qty:,.0f}",
                "עלות קנייה ממוצעת": f"{currency_sym}{avg_buy_cost:,.2f}",
                "מחיר שוק נוכחי": f"{currency_sym}{curr_market_price:,.2f}",
                "שינוי יומי (היום)": f"{daily_chg:+.2f}%",     # פיתוח מבוקש 1
                "תשואה מצטברת (ROI)": f"{roi_pct:+.2f}%", # פיתוח מבוקש 1
                "זמן פוזיציה": time_string
            })
                
    if holding_rows:
        st.dataframe(pd.DataFrame(holding_rows).set_index("סימול מניה"), use_container_width=True)
    else:
        st.info("אין כרגע מניות בתיק שלך. בצע רכישה מטה כדי להתחיל.")
        
    cw1, cw2, cw3 = st.columns(3)
    cw1.metric("💵 יתרת מזומן פנויה (ILS)", f"₪{user_db['cash_ils']:,.2f}")
    cw2.metric("📦 שווי החזקות במניות (ILS)", f"₪{portfolio_val_ils:,.2f}")
    cw3.metric("👑 שווי תיק כולל (Net Worth)", f"₪{total_net_worth_ils:,.2f}")
    st.markdown("---")

    # חדר עסקאות וביצוע פקודות
    if ticker_1:
        df1, stock_obj1 = load_stock_data(ticker_1)
        if not df1.empty and stock_obj1 and len(df1) > 20:
            is_ta = ".TA" in ticker_1
            res1 = analyze_ticker(df1, risk_profile, is_ta, stock_obj1)
            curr_price_normalized = res1['current_price']
            
            st.subheader(f"ℹ️ חדר מסחר וביצוע עסקאות עבור: {ticker_1}")
            tc1, tc2, tc3 = st.columns(3)
            holding_info = user_db["portfolio"].get(ticker_1, {"qty": 0, "avg_price_source": 0.0, "first_buy_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
            user_shares = holding_info["qty"]
            
            with tc1:
                t_qty = st.number_input("כמות יחידות לביצוע:", min_value=1, value=10, step=1)
                st.caption(f"מטבע פקודה: {'ILS (₪)' if is_ta else 'USD ($)'}")
            
            with tc2:
                st.write(""); st.write("")
                gross_cost_ils = t_qty * curr_price_normalized * (1.0 if is_ta else usd_ils)
                commission_ils = gross_cost_ils * COMMISSION_RATE
                
                if st.button("🟢 בצע פקודת קנייה", use_container_width=True):
                    total_charge_ils = gross_cost_ils + commission_ils
                    if user_db["cash_ils"] >= total_charge_ils:
                        user_db["cash_ils"] -= total_charge_ils
                        
                        # --- פיתוח מבוקש 2: שכלול וחישוב מחיר קנייה ממוצע משוקלל ---
                        old_qty = holding_info["qty"]
                        old_avg = holding_info["avg_price_source"]
                        new_qty = old_qty + t_qty
                        
                        if old_qty > 0:
                            # נוסחת ממוצע משוקלל
                            weighted_avg_price = ((old_qty * old_avg) + (t_qty * curr_price_normalized)) / new_qty
                            b_time = holding_info.get("first_buy_time", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                        else:
                            weighted_avg_price = curr_price_normalized
                            b_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            
                        user_db["portfolio"][ticker_1] = {"qty": new_qty, "avg_price_source": weighted_avg_price, "first_buy_time": b_time}
                        save_user_data(current_user, user_db)
                        add_to_history(current_user, ticker_1, "BUY", t_qty, curr_price_normalized, (1.0 if is_ta else usd_ils), commission_ils, 0.0, total_charge_ils)
                        st.success("הקנייה בוצעה ושוקלל ממוצע עלות חדש."); st.rerun()
                    else: st.error("אין מספיק שקלים בארנק.")
                        
                if st.button("🔴 בצע פקודת מכירה", use_container_width=True):
                    if holding_info["qty"] >= t_qty:
                        profit_source = (curr_price_normalized - holding_info["avg_price_source"]) * t_qty
                        tax_ils = (profit_source * (1.0 if is_ta else usd_ils) * TAX_RATE) if profit_source > 0 else 0.0
                        total_receive_ils = gross_cost_ils - commission_ils - tax_ils
                        
                        user_db["cash_ils"] += total_receive_ils
                        user_db["portfolio"][ticker_1]["qty"] -= t_qty
                        if user_db["portfolio"][ticker_1]["qty"] == 0: 
                            del user_db["portfolio"][ticker_1]
                        save_user_data(current_user, user_db)
                        add_to_history(current_user, ticker_1, "SELL", t_qty, curr_price_normalized, (1.0 if is_ta else usd_ils), commission_ils, tax_ils, total_receive_ils)
                        st.success("המכירה בוצעה בהצלחה."); st.rerun()
                    else: st.error("אין מספיק מניות ברשותך.")

            with tc3:
                symbol_lbl = "₪" if is_ta else "$"
                st.info(f"ברשותך כרגע **{user_shares}** מניות.\n\nמחיר שוק: **{symbol_lbl}{curr_price_normalized:,.2f}**")

            # תצוגת גרף נרות
            df = res1['df']
            fig = make_subplots(rows=1, cols=1)
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close']))
            fig.update_layout(xaxis_rangeslider_visible=False, template="plotly_dark", height=320, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

    # היסטוריית פעולות
    st.markdown("---")
    st.subheader("📜 יומן פעולות והיסטוריית עסקאות מלאה")
    hist_df = load_user_history(current_user)
    if not hist_df.empty: st.dataframe(hist_df, use_container_width=True)

render_realtime_simulator()
