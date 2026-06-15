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
# חלק 1: הגדרות דף, בסיס נתונים SQLite ואבטחת משתמשים
# =========================================================
st.set_page_config(page_title="סימולטור השקעות ומניות מובילות", layout="wide")

DB_FILE = "simulator_users.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, cash REAL, portfolio TEXT, orders TEXT)''')
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
    c.execute("INSERT INTO users VALUES (?, ?, 10000.0, '{}', '[]')", (username, hash_password(password)))
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
    c.execute("SELECT cash, portfolio, orders FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"cash": row[0], "portfolio": json.loads(row[1]), "orders": json.loads(row[2])}
    return {"cash": 10000.0, "portfolio": {}, "orders": []}

def save_user_data(username, data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET cash=?, portfolio=?, orders=? WHERE username=?", 
              (data["cash"], json.dumps(data["portfolio"]), json.dumps(data["orders"]), username))
    conn.commit()
    conn.close()

init_db()
# --- תצוגת מדדים מובילים בראש העמוד ---
def render_top_market_indices():
    indices = {"S&P 500": "^GSPC", "Nasdaq 100": "^NDX", "Dow Jones": "^DJI", "Bitcoin": "BTC-USD"}
    cols = st.columns(len(indices))
    for i, (name, ticker) in enumerate(indices.items()):
        try:
            df = yf.Ticker(ticker).history(period="2d")
            if len(df) >= 2:
                close_today = df['Close'].iloc[-1]
                close_yesterday = df['Close'].iloc[-2]
                pct_change = ((close_today - close_yesterday) / close_yesterday) * 100
                cols[i].metric(name, f"${close_today:,.2f}", f"{pct_change:+.2f}%")
            else: cols[i].metric(name, "טוען...")
        except: cols[i].metric(name, "שגיאה")

st.title("📈 סימולטור השקעות ומנוע מניות מובילות")
render_top_market_indices()
st.markdown("---")

if 'logged_in_user' not in st.session_state:
    st.session_state['logged_in_user'] = None

if st.session_state['logged_in_user'] is None:
    st.subheader("🔐 התחברות או רישום למערכת הסימולטור")
    auth_tab1, auth_tab2 = st.tabs(["🔑 התחברות", "📝 הרשמה למשתמש חדש"])
    
    with auth_tab1:
        login_user_input = st.text_input("שם משתמש:", key="login_user").strip()
        login_pass_input = st.text_input("סיסמה:", type="password", key="login_pass").strip()
        if st.button("התחבר למערכת", use_container_width=True):
            if login_user_input and login_pass_input and login_user(login_user_input, login_pass_input):
                st.session_state['logged_in_user'] = login_user_input
                st.success(f"ברוך הבא, {login_user_input}!")
                st.rerun()
            else: st.error("שם משתמש או סיסמה שגויים.")
                
    with auth_tab2:
        reg_user_input = st.text_input("בחר שם משתמש:", key="reg_user").strip()
        reg_pass_input = st.text_input("בחר סיסמה:", type="password", key="reg_pass").strip()
        if st.button("צור חשבון חדש", use_container_width=True):
            if reg_user_input and reg_pass_input:
                if register_user(reg_user_input, reg_pass_input): st.success("החשבון נוצר! בצע התחברות.")
                else: st.error("שם המשתמש תפוס.")
            else: st.warning("אנא מלא את כל השדות.")
    st.stop()

current_user = st.session_state['logged_in_user']
user_db = load_user_data(current_user)

st.sidebar.subheader(f"👋 מחובר: {current_user}")
if st.sidebar.button("🚪 התנתק"):
    st.session_state['logged_in_user'] = None
    st.rerun()
st.sidebar.markdown("---")

st.sidebar.header("👤 הגדרות סימולטור")
risk_profile = st.sidebar.selectbox(":רמת סיכון", ["(Aggressive (אגרסיבי", "(Moderate (מאוזן ", "(Conservative (סולידי"], index=1)
investment_amount = st.sidebar.number_input("(($) סכום בסיס:", min_value=100, value=int(user_db["cash"]), step=500)
risk_percent = st.sidebar.slider(":(%) אחוז סיכון", min_value=0.5, max_value=5.0, value=2.0, step=0.5)
ticker_1 = st.sidebar.text_input("🔍 הזן סימול מניה", value="AAPL").upper().strip()

end_date = datetime.today()
start_date = end_date - timedelta(days=365 * 2)
def load_stock_data(ticker_symbol, start, end):
    if not ticker_symbol: return pd.DataFrame(), None
    try:
        stock_obj = yf.Ticker(ticker_symbol)
        return stock_obj.history(start=start, end=end, auto_adjust=True), stock_obj
    except: return pd.DataFrame(), None

def get_sector_leaderboard(sector_name):
    """שליפה ודירוג של המניות החזקות ביותר במשק לפי הסקטור הנבחר"""
    sector_map = {
        "טכנולוגיה (Technology)": ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META"],
        "בריאות (Healthcare)": ["JNJ", "LLY", "PFE", "UNH", "MRK", "ABV"],
        "אנרגיה (Energy)": ["XOM", "CVX", "COP", "SLB", "EOG", "MPC"],
        "פיננסים (Financials)": ["JPM", "BAC", "WFC", "MS", "GS", "V"]
    }
    
    tickers = sector_map.get(sector_name, sector_map["טכנולוגיה (Technology)"])
    leaderboard_rows = []
    
    for tick in tickers:
        try:
            stock = yf.Ticker(tick)
            df = stock.history(period="5d")
            if not df.empty and len(df) >= 2:
                current_price = df['Close'].iloc[-1]
                yesterday_price = df['Close'].iloc[-2]
                daily_change = ((current_price - yesterday_price) / yesterday_price) * 100
                
                # שליפת תשואה שבועית פשוטה
                oldest_price = df['Close'].iloc[0]
                weekly_change = ((current_price - oldest_price) / oldest_price) * 100
                
                leaderboard_rows.append({
                    "סימול מניה": tick,
                    "שם החברה": stock.info.get('longName', tick),
                    "מחיר נוכחי": f"${current_price:,.2f}",
                    "שינוי יומי": f"{daily_change:+.2f}%",
                    "תשואה שבועית": f"{weekly_change:+.2f}%",
                    "raw_change": daily_change # לטובת המיון
                })
        except: pass
        
    return leaderboard_rows

def calculate_periodic_returns(ticker_symbol):
    try:
        stock = yf.Ticker(ticker_symbol)
        df = stock.history(period="1y")
        if df.empty or len(df) < 5: return None
        current_price = df['Close'].iloc[-1]
        
        def get_pct(days_ago):
            idx = max(0, len(df) - days_ago)
            old_price = df['Close'].iloc[idx]
            return ((current_price - old_price) / old_price) * 100

        return {
            "שבוע אחרון": f"{get_pct(5):+.2f}%",
            "חודש אחרון": f"{get_pct(21):+.2f}%",
            "חצי שנה": f"{get_pct(126):+.2f}%",
            "שנה אחרונה": f"{get_pct(len(df)-1):+.2f}%"
        }
    except: return None

def check_and_execute_user_orders(username, data):
    updated_orders = []
    executed_any = False
    for order in data.get("orders", []):
        tick, target, o_type, qty = order["ticker"], order["target_price"], order["type"], order["qty"]
        df, _ = load_stock_data(tick, datetime.today() - timedelta(days=5), datetime.today())
        if df.empty:
            updated_orders.append(order)
            continue
        curr_price = float(df['Close'].iloc[-1])
        if o_type == "BUY_LIMIT" and curr_price <= target:
            if data["cash"] >= curr_price * qty:
                data["cash"] -= curr_price * qty
                data["portfolio"][tick] = data["portfolio"].get(tick, 0) + qty
                executed_any = True
        elif o_type == "SELL_LIMIT" and curr_price >= target:
            if data["portfolio"].get(tick, 0) >= qty:
                data["cash"] += curr_price * qty
                data["portfolio"][tick] -= qty
                if data["portfolio"][tick] == 0: del data["portfolio"][tick]
                executed_any = True
        else: updated_orders.append(order)
    if executed_any:
        data["orders"] = updated_orders
        save_user_data(username, data)
        return True
    return False

def calculate_portfolio_value(portfolio):
    total_val = 0.0
    shares_values = {}
    for tick, qty in portfolio.items():
        if qty <= 0: continue
        df, _ = load_stock_data(tick, datetime.today() - timedelta(days=5), datetime.today())
        if not df.empty:
            price = float(df['Close'].iloc[-1])
            total_val += price * qty
            shares_values[tick] = price * qty
    return total_val, shares_values
def analyze_ticker(df, selected_risk_profile):
    df['MA200'] = df['Close'].rolling(window=200).mean()
    df['BB_Middle'] = df['Close'].rolling(window=20).mean()
    df['BB_Std'] = df['Close'].rolling(window=20).std()
    df['BB_Lower'] = df['BB_Middle'] - (2 * df['BB_Std'])
    current_price = float(df['Close'].iloc[-1])
    ma200_curr = df['MA200'].iloc[-1]
    bb_lower_curr = df['BB_Lower'].iloc[-1]
    
    reasons = []
    score = 1 if current_price > ma200_curr else -1
    reasons.append(f"המניה מעל ממוצע 200" if score > 0 else "המניה מתחת לממוצע 200")
    
    buy_threshold, sl_multiplier = (2, 0.98) if "סולידי" in selected_risk_profile else ((0, 0.94) if "אגרסיבי" in selected_risk_profile else (1, 0.96))
    verdict, v_type = ("הזדמנות קנייה (Buy)", "BUY") if score >= buy_threshold else (("להמתין לירידה (Wait)", "WAIT") if score < 0 else ("החזק / ניטרלי (Hold)", "HOLD"))
    
    return {"df": df, "verdict": verdict, "verdict_type": v_type, "current_price": current_price, "current_rsi": 50.0, "waiting_target": bb_lower_curr, "stop_loss_price": bb_lower_curr * sl_multiplier, "analysis_reasons": reasons}

# =========================================================
# חלק 4: ממשק המשתמש והרצת המערכת
# =========================================================
@st.fragment(run_every=60)
def render_realtime_simulator():
    global user_db
    if check_and_execute_user_orders(current_user, user_db):
        user_db = load_user_data(current_user)
        
    portfolio_val, holdings_distribution = calculate_portfolio_value(user_db["portfolio"])
    total_net_worth = user_db["cash"] + portfolio_val
    
    # --- תצוגת דירוג המניות החזקות במשק לפי סקטור ---
    st.subheader("🏆 דירוג המניות החזקות והמובילות במשק")
    sector_choice = st.selectbox("בחר תחום (סקטור) להצגת המניות החזקות ביותר:", 
                                 ["טכנולוגיה (Technology)", "בריאות (Healthcare)", "אנרגיה (Energy)", "פיננסים (Financials)"])
    
    with st.spinner("סורק את מניות השקף המובילות..."):
        sector_leaders = get_sector_leaderboard(sector_choice)
        
    if sector_leaders:
        leaders_df = pd.DataFrame(sector_leaders)
        leaders_df = leaders_df.sort_values(by="raw_change", ascending=False).reset_index(drop=True)
        leaders_df.index += 1 # דירוג מ-1
        st.dataframe(leaders_df[["סימול מניה", "שם החברה", "מחיר נוכחי", "שינוי יומי", "תשואה שבועית"]], use_container_width=True)
    st.markdown("---")

    # חדר מסחר אישי
    st.subheader(f"💼 חדר המסחר האישי של: {current_user}")
    col_w1, col_w2, col_w3 = st.columns(3)
    col_w1.metric("💵 מזומן פנוי במסחר", f"${user_db['cash']:,.2f}")
    col_w2.metric("📦 שווי מניות נוכחי", f"${portfolio_val:,.2f}")
    col_w3.metric("👑 שווי תיק כולל", f"${total_net_worth:,.2f}")

    if ticker_1:
        df1, stock_obj1 = load_stock_data(ticker_1, start_date, end_date)
        if not df1.empty and stock_obj1:
            res1 = analyze_ticker(df1, risk_profile)
            info = stock_obj1.info
            
            st.subheader(f"ℹ️ על החברה וביצועי מניית {ticker_1}")
            with st.expander(f"🔍 קרא הסבר כללי על חברת {info.get('longName', ticker_1)} וביצועי עבר"):
                st.write(f"**תחום פעילות (Sector):** {info.get('sector', 'N/A')} | **תעשייה:** {info.get('industry', 'N/A')}")
                st.write(f"**תיאור עסקי:** {info.get('longBusinessSummary', 'אין תיאור זמין כעת.')}")
                
                returns_data = calculate_periodic_returns(ticker_1)
                if returns_data:
                    st.write("**📊 טבלת תשואות היסטוריות לתקופות זמן:**")
                    st.table(pd.DataFrame([returns_data]))

            # חדר מסחר
            st.subheader(f"🎛️ פאנל ביצוע עסקאות")
            tc1, tc2, tc3 = st.columns(3)
            curr_stock_price = res1['current_price']
            user_shares = user_db["portfolio"].get(ticker_1, 0.0)
            
            with tc1:
                trade_qty = st.number_input("כמות מניות לפעולה:", min_value=1, value=10, step=1)
                action_mode = st.radio("סוג פעולה:", ["ביצוע מיידי (Market)", "פקודה עתידית (Limit)"])
                target_price = st.number_input("מחיר יעד ($):", min_value=0.01, value=curr_stock_price, step=0.5) if action_mode == "פקודה עתידית (Limit)" else curr_stock_price
                    
            with tc2:
                st.write(""); st.write("")
                if st.button("🟢 שלח פקודת קנייה", use_container_width=True):
                    if action_mode == "ביצוע מיידי (Market)":
                        if user_db["cash"] >= trade_qty * curr_stock_price:
                            user_db["cash"] -= trade_qty * curr_stock_price
                            user_db["portfolio"][ticker_1] = user_db["portfolio"].get(ticker_1, 0.0) + trade_qty
                            save_user_data(current_user, user_db); st.rerun()
                        else: st.error("אין מספיק מזומן.")
                    else:
                        user_db["orders"].append({"ticker": ticker_1, "type": "BUY_LIMIT", "target_price": target_price, "qty": trade_qty})
                        save_user_data(current_user, user_db); st.rerun()
                        
                if st.button("🔴 שלח פקודת מכירה", use_container_width=True):
                    if action_mode == "ביצוע מיידי (Market)":
                        if user_shares >= trade_qty:
                            user_db["cash"] += trade_qty * curr_stock_price
                            user_db["portfolio"][ticker_1] -= trade_qty
                            if user_db["portfolio"][ticker_1] == 0: del user_db["portfolio"][ticker_1]
                            save_user_data(current_user, user_db); st.rerun()
                        else: st.error("אין מספיק מניות.")
                    else:
                        if user_shares >= trade_qty:
                            user_db["orders"].append({"ticker": ticker_1, "type": "SELL_LIMIT", "target_price": target_price, "qty": trade_qty})
                            save_user_data(current_user, user_db); st.rerun()

            with tc3:
                st.info(f"ברשותך כרגע **{user_shares}** מניות.\n\nמחיר שוק: **${curr_stock_price:.2f}**")

            # המלצות וגרף
            st.markdown("---")
            st.subheader(f"📊 המלצות מערכת ומחשבון סיכונים")
            st.metric("סטטוס מערכת", res1['verdict'])
            
            fig = make_subplots(rows=1, cols=1)
            fig.add_trace(go.Candlestick(x=df1.index, open=df1['Open'], high=df1['High'], low=df1['Low'], close=df1['Close']))
            fig.update_layout(xaxis_rangeslider_visible=False, template="plotly_dark", height=300)
            st.plotly_chart(fig, use_container_width=True)

render_realtime_simulator()
