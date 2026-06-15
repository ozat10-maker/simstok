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
# חלק 1: הגדרות דף, בסיס נתונים קבוע בשרת (SQLite) ומיסוי
# =========================================================
st.set_page_config(page_title="סימולטור השקעות מקצועי", layout="wide")

# שימוש בנתיב /tmp/ מונע מהקובץ להימחק ברענוני שרת רגילים ב-Streamlit Cloud
DB_FILE = "/tmp/simulator_pro_v3.db"
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
            else: st.error("שם משתמש או סיסמה שגויים או שהשרת אותחל. נסה להירשם מחדש במידת הצורך.")
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
        df = stock_obj.history(period="2y", auto_adjust=True)
        return df, stock_obj
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
        return {"שבוע אחרון": f"{get_pct(5):+.2f}%", "חודש אחרון": f"{get_pct(21):+.2f}%", "חצי שנה": f"{get_pct(126):+.2f}%", "שנה אחרונה": f"{get_pct(len(df)-1):+.2f}%"}
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

def analyze_ticker(df, selected_risk_profile):
    df['MA200'] = df['Close'].rolling(window=200).mean()
    df['BB_Middle'] = df['Close'].rolling(window=20).mean()
    df['BB_Std'] = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['BB_Middle'] + (2 * df['BB_Std'])
    df['BB_Lower'] = df['BB_Middle'] - (2 * df['BB_Std'])
    
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['RSI'] = 100 - (100 / (1 + (gain / (loss + 0.0001))))
    
    current_price = float(df['Close'].iloc[-1])
    current_rsi = df['RSI'].iloc[-1] if pd.notna(df['RSI'].iloc[-1]) else 50.0
    ma200_curr = df['MA200'].iloc[-1] if pd.notna(df['MA200'].iloc[-1]) else current_price
    bb_lower_curr = df['BB_Lower'].iloc[-1] if pd.notna(df['BB_Lower'].iloc[-1]) else current_price * 0.95
    
    reasons = []
    score = 0
    if current_price > ma200_curr:
        score += 1
        reasons.append(f"המניה במגמה ראשית עולה (מעל ממוצע נע 200 השוכן ב- ${ma200_curr:.2f}).")
    else:
        score -= 1
        reasons.append(f"המניה במגמת ירידה ארוכת טווח (מתחת לממוצע נע 200).")
        
    if current_price <= (bb_lower_curr * 1.02):
        score += 1
        reasons.append("המחיר זול סטטיסטית וקרוב לרצועת בולינגר התחתונה.")
        
    buy_threshold, sl_multiplier = (2, 0.98) if "סולידי" in selected_risk_profile else ((0, 0.94) if "אגרסיבי" in selected_risk_profile else (1, 0.96))
    verdict, v_type = ("הזדמנות קנייה (Buy)", "BUY") if score >= buy_threshold else (("להמתין לירידה (Wait)", "WAIT") if score < 0 else ("החזק / ניטרלי (Hold)", "HOLD"))
    stop_loss = bb_lower_curr * sl_multiplier
    
    return {"df": df, "verdict": verdict, "verdict_type": v_type, "current_price": current_price, "current_rsi": current_rsi, "waiting_target": bb_lower_curr, "stop_loss_price": stop_loss, "analysis_reasons": reasons}
# =========================================================
# חלק 4: ממשק משתמש, רשימת מעקב, דוחות מס והפלט האנליטי
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
        
    # רשימת מעקב
    st.subheader("⭐ רשימת המעקב האישית שלי")
    if user_db["watchlist"]:
        wl_data = []
        for w_tick in user_db["watchlist"]:
            df, _ = load_stock_data(w_tick)
            if not df.empty:
                wl_data.append({"סימול": w_tick, "מחיר שוק": f"${df['Close'].iloc[-1]:,.2f}", "נפח מסחר": f"{df['Volume'].iloc[-1]:,.0f}"})
        st.table(pd.DataFrame(wl_data))
    else: st.info("רשימת המעקב שלך ריקה כרגע.")

    # מצב חשבון
    st.subheader(f"💼 חדר מסחר מקצועי - משתמש: {current_user}")
    cw1, cw2, cw3 = st.columns(3)
    cw1.metric("💵 יתרת מזומן פנויה (ILS)", f"₪{user_db['cash_ils']:,.2f}")
    cw2.metric("📦 שווי החזקות במניות (ILS)", f"₪{portfolio_val_ils:,.2f}")
    cw3.metric("👑 שווי תיק כולל (Net Worth)", f"₪{total_net_worth_ils:,.2f}")

    if ticker_1:
        df1, stock_obj1 = load_stock_data(ticker_1)
        if not df1.empty and stock_obj1 and len(df1) > 20:
            res1 = analyze_ticker(df1, risk_profile)
            info = stock_obj1.info
            curr_usd = res1['current_price']
            
            # ניהול כפתור רשימת מעקב
            if ticker_1 not in user_db["watchlist"]:
                if st.button(f"➕ הוסף את {ticker_1} לרשימת המעקב"):
                    user_db["watchlist"].append(ticker_1)
                    save_user_data(current_user, user_db); st.rerun()
            else:
                if st.button(f"➖ הסר את {ticker_1} מרשימת המעקב"):
                    user_db["watchlist"].remove(ticker_1)
                    save_user_data(current_user, user_db); st.rerun()

            # --- תצוגת כרטיס המידע והסבר על המניה (תוקן והוחזר) ---
            st.subheader(f"ℹ️ על החברה וביצועי מניית {ticker_1}")
            with st.expander(f"🔍 קרא הסבר כללי על חברת {info.get('longName', ticker_1)} וביצועי עבר", expanded=True):
                st.write(f"**תחום פעילות:** {info.get('sector', 'N/A')} | **תעשייה:** {info.get('industry', 'N/A')}")
                st.write(f"**תיאור עסקי:** {info.get('longBusinessSummary', 'אין תיאור זמין כעת.')}")
                
                returns_data = calculate_periodic_returns(ticker_1)
                if returns_data:
                    st.write("**📊 טבלת תשואות היסטוריות לתקופות זמן:**")
                    st.table(pd.DataFrame([returns_data]))

            # חדר מסחר
            st.subheader(f"🎛️ פאנל ביצוע עסקאות")
            tc1, tc2, tc3 = st.columns(3)
            user_shares = user_db["portfolio"].get(ticker_1, {"qty": 0, "avg_price_usd": 0.0})["qty"]
            
            with tc1:
                t_qty = st.number_input("כמות יחידות לביצוע:", min_value=1, value=10, step=1)
                action_mode = st.radio("סוג פעולה:", ["ביצוע מיידי (Market)", "פקודה עתידית (Limit)"])
                target_price = st.number_input("מחיר יעד ($):", min_value=0.01, value=curr_usd, step=0.5) if action_mode == "פקודה עתידית (Limit)" else curr_usd
                    
            with tc2:
                st.write(""); st.write("")
                gross_cost_ils = t_qty * curr_usd * usd_ils
                commission_ils = gross_cost_ils * COMMISSION_RATE
                
                if st.button("🟢 בצע פקודת קנייה", use_container_width=True):
                    total_charge_ils = gross_cost_ils + commission_ils
                    if user_db["cash_ils"] >= total_charge_ils:
                        user_db["cash_ils"] -= total_charge_ils
                        holding_info = user_db["portfolio"].get(ticker_1, {"qty": 0, "avg_price_usd": 0.0})
                        new_qty = holding_info["qty"] + t_qty
                        new_avg = ((holding_info["qty"] * holding_info["avg_price_usd"]) + (t_qty * curr_usd)) / new_qty
                        user_db["portfolio"][ticker_1] = {"qty": new_qty, "avg_price_usd": new_avg}
                        save_user_data(current_user, user_db)
                        add_to_history(current_user, ticker_1, "BUY", t_qty, curr_usd, usd_ils, commission_ils, 0.0, total_charge_ils)
                        st.success("הקנייה בוצעה."); st.rerun()
                    else: st.error("אין מספיק שקלים.")
                        
                if st.button("🔴 בצע פקודת מכירה", use_container_width=True):
                    holding_info = user_db["portfolio"].get(ticker_1, {"qty": 0, "avg_price_usd": 0.0})
                    if holding_info["qty"] >= t_qty:
                        profit_usd = (curr_usd - holding_info["avg_price_usd"]) * t_qty
                        tax_ils = (profit_usd * usd_ils * TAX_RATE) if profit_usd > 0 else 0.0
                        total_receive_ils = gross_cost_ils - commission_ils - tax_ils
                        
                        user_db["cash_ils"] += total_receive_ils
                        user_db["portfolio"][ticker_1]["qty"] -= t_qty
                        if user_db["portfolio"][ticker_1]["qty"] == 0: del user_db["portfolio"][ticker_1]
                        save_user_data(current_user, user_db)
                        add_to_history(current_user, ticker_1, "SELL", t_qty, curr_usd, usd_ils, commission_ils, tax_ils, total_receive_ils)
                        st.success("המכירה בוצעה והמס נוכה."); st.rerun()
                    else: st.error("אין מספיק מניות.")

            with tc3:
                st.info(f"ברשותך כרגע **{user_shares}** מניות.\n\nמחיר שוק: **${curr_usd:.2f}**")

            # --- תצוגת דוחות הניתוח, ההמלצה והגרף הטכני המלא (תוקן והוחזר) ---
            st.markdown("---")
            st.subheader(f"📊 המלצות מערכת ומחשבון סיכונים עבור {ticker_1}")
            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric("החלטת מנוע", res1['verdict'])
            col_m2.metric("מדד RSI", f"{res1['current_rsi']:.1f}")
            col_m3.metric("קטיעת הפסד מומלצת (SL)", f"${res1['stop_loss_price']:.2f}")
            
            st.write("**🧠 סיכום הממצאים הטכניים:**")
            for r in res1['analysis_reasons']: 
                st.write(f"• {r}")
            
            # הצגת הגרף הפיננסי
            df = res1['df']
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06, row_heights=[0.7, 0.3])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close']), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['BB_Middle'], line=dict(color='cyan', width=1), name="בולינגר"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='purple', width=1.2), name="RSI"), row=2, col=1)
            fig.update_layout(xaxis_rangeslider_visible=False, template="plotly_dark", height=380, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.error("לא נמצאו מספיק נתונים היסטוריים להצגת הגרף והניתוח של מניה זו.")

    # היסטוריית פעולות
    st.markdown("---")
    st.subheader("📜 יומן פעולות והיסטוריית עסקאות מלאה")
    hist_df = load_user_history(current_user)
    if not hist_df.empty: st.dataframe(hist_df, use_container_width=True)
    else: st.info("לא בוצעו עסקאות בחשבון זה עדיין.")

render_realtime_simulator()
