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
# חלק 1: הגדרות דף, בסיס נתונים SQLite משודרג לזמני פוזיציות
# =========================================================
st.set_page_config(page_title="סימולטור השקעות מקצועי", layout="wide")

DB_FILE = "/tmp/simulator_pro_v5.db"
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
        return {"cash_ils": row, "portfolio": json.loads(row), "orders": json.loads(row), "watchlist": json.loads(row)}
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
        return float(df['Close'].iloc[-1]) if not df.empty else 3.70
    except:
        return 3.70

def render_top_market_indices():
    indices = {"S&P 500": "^GSPC", "Nasdaq 100": "^NDX", "מדד ת\"א 125": "^TA125.TA", "Bitcoin": "BTC-USD"}
    cols = st.columns(len(indices))
    for i, (name, ticker) in enumerate(indices.items()):
        try:
            df = yf.Ticker(ticker).history(period="2d")
            if len(df) >= 2:
                close_today = df['Close'].iloc[-1]
                close_yesterday = df['Close'].iloc[-2]
                if ".TA" in ticker:  
                    close_today /= 100
                    close_yesterday /= 100
                pct_change = ((close_today - close_yesterday) / close_yesterday) * 100
                cols[i].metric(name, f"${close_today:,.2f}" if "$" in name or "Bitcoin" in name else f"₪{close_today:,.2f}", f"{pct_change:+.2f}%")
            else: cols[i].metric(name, "טוען...")
        except: cols[i].metric(name, "שגיאה")

st.title("📈 סימולטור מסחר עם טבלת פוזיציות מתקדמת וניתוח זמנים")
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

def calculate_time_elapsed(buy_timestamp_str):
    """חישוב דינמי של הזמן שחלף מאז קניית המניה והצגתו במלל קריא"""
    try:
        buy_time = datetime.strptime(buy_timestamp_str, '%Y-%m-%d %H:%M:%S')
        diff = datetime.now() - buy_time
        if diff.days > 0:
            return f"{diff.days} ימים"
        hours = diff.seconds // 3600
        if hours > 0:
            return f"{hours} שעות"
        minutes = (diff.seconds % 3600) // 60
        return f"{minutes} דקות"
    except:
        return "N/A"

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
            df, _ = load_stock_data(tick)
            if not df.empty and len(df) >= 2:
                c_p = df['Close'].iloc[-1]
                if ".TA" in tick: c_p /= 100
                symbol_display = "₪" if ".TA" in tick else "$"
                rows.append({"סימול": tick, "מחיר": f"{symbol_display}{c_p:,.2f}"})
        except: pass
    return rows

def analyze_ticker(df, selected_risk_profile, is_ils_stock):
    df['MA200'] = df['Close'].rolling(window=200).mean()
    df['BB_Middle'] = df['Close'].rolling(window=20).mean()
    df['BB_Std'] = df['Close'].rolling(window=20).std()
    df['BB_Lower'] = df['BB_Middle'] - (2 * df['BB_Std'])
    current_price = float(df['Close'].iloc[-1])
    ma200_curr = df['MA200'].iloc[-1] if pd.notna(df['MA200'].iloc[-1]) else current_price
    bb_lower_curr = df['BB_Lower'].iloc[-1] if pd.notna(df['BB_Lower'].iloc[-1]) else current_price * 0.95
    if is_ils_stock:
        current_price /= 100
        ma200_curr /= 100
        bb_lower_curr /= 100
    reasons = []
    score = 1 if current_price > ma200_curr else -1
    reasons.append(f"המניה במגמה ראשית עולה." if score > 0 else "המניה במגמת ירידה ארוכת טווח.")
    buy_threshold, sl_multiplier = (2, 0.98) if "סולידי" in selected_risk_profile else ((0, 0.94) if "אגרסיבי" in selected_risk_profile else (1, 0.96))
    verdict, v_type = ("הזדמנות קנייה (Buy)", "BUY") if score >= buy_threshold else (("להמתין לירידה (Wait)", "WAIT") if score < 0 else ("החזק / ניטרלי (Hold)", "HOLD"))
    return {"df": df, "verdict": verdict, "verdict_type": v_type, "current_price": current_price, "current_rsi": 50.0, "waiting_target": bb_lower_curr, "stop_loss_price": bb_lower_curr * sl_multiplier, "analysis_reasons": reasons}
# =========================================================
# חלק 4: ממשק משתמש, טבלת החזקות משודרגת, מיסוי וביצוע עסקאות
# =========================================================
@st.fragment(run_every=60)
def render_realtime_simulator():
    global user_db, usd_ils, ticker_1
    
    # --- בנייה ותצוגה של טבלת תיק המסחר הדינמית והמפורטת ---
    st.subheader("💼 תיק ההשקעות ומצבת פוזיציות פתוחות")
    portfolio_val_ils = 0.0
    holding_rows = []
    
    for tick, info in user_db["portfolio"].items():
        qty = info.get("qty", 0)
        if qty <= 0: continue
        
        df, _ = load_stock_data(tick)
        if not df.empty:
            price_raw = float(df['Close'].iloc[-1])
            is_ta_asset = ".TA" in tick
            
            # נירמול שערים ומטבעות
            if is_ta_asset:
                curr_market_price = price_raw / 100
                asset_val_ils = curr_market_price * qty
                currency_sym = "₪"
            else:
                curr_market_price = price_raw
                asset_val_ils = price_raw * qty * usd_ils
                currency_sym = "$"
                
            portfolio_val_ils += asset_val_ils
            avg_buy_cost = info.get("avg_price_source", 0.0)
            
            # חישוב תשואה מצטברת ריאלית עבור נייר הערך
            roi_pct = ((curr_market_price - avg_buy_cost) / avg_buy_cost) * 100 if avg_buy_cost > 0 else 0.0
            time_string = calculate_time_elapsed(info.get("first_buy_time", datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            
            holding_rows.append({
                "סימול מניה": tick,
                "כמות יחידות": f"{qty:,.0f}",
                "עלות קנייה (ליחידה)": f"{currency_sym}{avg_buy_cost:,.2f}",
                "מחיר שוק נוכחי": f"{currency_sym}{curr_market_price:,.2f}",
                "תשואה מצטברת": f"{roi_pct:+.2f}%",
                "זמן פוזיציה": time_string
            })
            
    total_net_worth_ils = user_db["cash_ils"] + portfolio_val_ils
    
    if holding_rows:
        st.dataframe(pd.DataFrame(holding_rows).set_index("סימול מניה"), use_container_width=True)
    else:
        st.info("אין כרגע מניות או פוזיציות פתוחות בתיק שלך. בצע רכישה ראשונה בפאנל מטה.")
        
    cw1, cw2, cw3 = st.columns(3)
    cw1.metric("💵 יתרת מזומן פנויה (ILS)", f"₪{user_db['cash_ils']:,.2f}")
    cw2.metric("📦 שווי החזקות במניות (ILS)", f"₪{portfolio_val_ils:,.2f}")
    cw3.metric("👑 שווי תיק כולל (Net Worth)", f"₪{total_net_worth_ils:,.2f}")
    st.markdown("---")

    # פאנל עסקאות וכרטיס מניה
    if ticker_1:
        df1, stock_obj1 = load_stock_data(ticker_1)
        if not df1.empty and stock_obj1 and len(df1) > 20:
            is_ta = ".TA" in ticker_1
            res1 = analyze_ticker(df1, risk_profile, is_ta)
            curr_price_normalized = res1['current_price']
            
            st.subheader(f"ℹ️ כרטיס מידע וביצוע עסקאות עבור: {ticker_1}")
            with st.expander(f"🔍 קרא הסבר כללי על החברה וביצועי עבר"):
                st.write(f"**תיאור עסקי:** {stock_obj1.info.get('longBusinessSummary', 'אין תיאור זמין כעת.')}")
                returns_data = calculate_periodic_returns(ticker_1)
                if returns_data: st.table(pd.DataFrame([returns_data]))

            tc1, tc2, tc3 = st.columns(3)
            with tc1:
                t_qty = st.number_input("כמות יחידות לביצוע:", min_value=1, value=10, step=1)
                st.caption(f"מטבע פעילות: {'שקלים חדשים (ILS)' if is_ta else 'דולר ארה\"ב (USD)'}")
            
            with tc2:
                st.write(""); st.write("")
                gross_cost_ils = t_qty * curr_price_normalized * (1.0 if is_ta else usd_ils)
                commission_ils = gross_cost_ils * COMMISSION_RATE
                
                if st.button("🟢 בצע פקודת קנייה", use_container_width=True):
                    total_charge_ils = gross_cost_ils + commission_ils
                    if user_db["cash_ils"] >= total_charge_ils:
                        user_db["cash_ils"] -= total_charge_ils
                        holding_info = user_db["portfolio"].get(ticker_1, {"qty": 0, "avg_price_source": 0.0, "first_buy_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
                        
                        new_qty = holding_info["qty"] + t_qty
                        new_avg = ((holding_info["qty"] * holding_info["avg_price_source"]) + (t_qty * curr_price_normalized)) / new_qty
                        b_time = holding_info.get("first_buy_time", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                        
                        user_db["portfolio"][ticker_1] = {"qty": new_qty, "avg_price_source": new_avg, "first_buy_time": b_time}
                        save_user_data(current_user, user_db)
                        add_to_history(current_user, ticker_1, "BUY", t_qty, curr_price_normalized, (1.0 if is_ta else usd_ils), commission_ils, 0.0, total_charge_ils)
                        st.success("הקנייה בוצעה."); st.rerun()
                    else: st.error("אין מספיק שקלים.")
                        
                if st.button("🔴 בצע פקודת מכירה", use_container_width=True):
                    holding_info = user_db["portfolio"].get(ticker_1, {"qty": 0, "avg_price_source": 0.0})
                    if holding_info["qty"] >= t_qty:
                        profit_source = (curr_price_normalized - holding_info["avg_price_source"]) * t_qty
                        tax_ils = (profit_source * (1.0 if is_ta else usd_ils) * TAX_RATE) if profit_source > 0 else 0.0
                        total_receive_ils = gross_cost_ils - commission_ils - tax_ils
                        
                        user_db["cash_ils"] += total_receive_ils
                        user_db["portfolio"][ticker_1]["qty"] -= t_qty
                        if user_db["portfolio"][ticker_1]["qty"] == 0: del user_db["portfolio"][ticker_1]
                        save_user_data(current_user, user_db)
                        add_to_history(current_user, ticker_1, "SELL", t_qty, curr_price_normalized, (1.0 if is_ta else usd_ils), commission_ils, tax_ils, total_receive_ils)
                        st.success("המכירה בוצעה."); st.rerun()
                    else: st.error("אין מספיק מניות.")

            with tc3:
                symbol_lbl = "₪" if is_ta else "$"
                st.info(f"מחיר שוק נוכחי: **{symbol_lbl}{curr_price_normalized:,.2f}**")

    st.markdown("---")
    st.subheader("📜 יומן פעולות והיסטוריית עסקאות מלאה")
    hist_df = load_user_history(current_user)
    if not hist_df.empty: st.dataframe(hist_df, use_container_width=True)

render_realtime_simulator()
