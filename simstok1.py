import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import sqlite3
import hashlib
from datetime import datetime, timedelta

# =========================================================
# חלק 1: הגדרות דף, בסיס נתונים SQLite ואבטחת משתמשים
# =========================================================
st.set_page_config(page_title="סימולטור השקעות רב-משתמשים", layout="wide")

DB_FILE = "simulator_users.db"

def init_db():
    """יצירת טבלאות בסיס הנתונים במידה ואינן קיימות"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # טבלת משתמשים
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, cash REAL, portfolio TEXT, orders TEXT)''')
    conn.commit()
    conn.close()

def hash_password(password):
    """הצפנת סיסמה למניעת שמירת טקסט חשוף"""
    return hashlib.sha256(password.encode()).hexdigest()

def register_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE username=?", (username,))
    if c.fetchone():
        conn.close()
        return False
    # משתמש חדש מקבל 10,000$ התחלתיים, תיק ריק ורשימת פקודות ריקה בפורמט JSON
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
        import json
        return {"cash": row[0], "portfolio": json.loads(row[1]), "orders": json.loads(row[2])}
    return {"cash": 10000.0, "portfolio": {}, "orders": []}

def save_user_data(username, data):
    import json
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET cash=?, portfolio=?, orders=? WHERE username=?", 
              (data["cash"], json.dumps(data["portfolio"]), json.dumps(data["orders"]), username))
    conn.commit()
    conn.close()

init_db()
# --- תצוגת מדדים מובילים בראש העמוד ---
def render_top_market_indices():
    """שליפת מדדים מובילים והצגתם כשורת כרטיסיות דינמית"""
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
            else:
                cols[i].metric(name, "טוען...")
        except:
            cols[i].metric(name, "שגיאת נתונים")

st.title("📈 סימולטור השקעות אישי ומאובטח")
render_top_market_indices()
st.markdown("---")

# --- מנגנון ניהול סשן התחברות ---
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
            else:
                st.error("שם משתמש או סיסמה שגויים.")
                
    with auth_tab2:
        reg_user_input = st.text_input("בחר שם משתמש:", key="reg_user").strip()
        reg_pass_input = st.text_input("בחר סיסמה חזקה:", type="password", key="reg_pass").strip()
        if st.button("צור חשבון חדש", use_container_width=True):
            if reg_user_input and reg_pass_input:
                if register_user(reg_user_input, reg_pass_input):
                    st.success("החשבון נוצר בהצלחה! כעת ניתן לעבור ללשונית התחברות.")
                else:
                    st.error("שם המשתמש כבר תפוס במערכת.")
            else:
                st.warning("אנא מלא את כל השדות.")
    st.stop() # עצירת ריצת שאר העמוד עד להתחברות

# אם הגענו לכאן, המשתמש מחובר
current_user = st.session_state['logged_in_user']

# קריאת הנתונים הספציפיים של המשתמש הנוכחי
user_db = load_user_data(current_user)

# --- (Sidebar) סרגל צדי למשתמש מחובר ---
st.sidebar.subheader(f"👋 מחובר כעת: {current_user}")
if st.sidebar.button("🚪 התנתק מהחשבון"):
    st.session_state['logged_in_user'] = None
    st.rerun()
st.sidebar.markdown("---")

st.sidebar.header("👤 פרופיל משקיע ורמת סיכון")
risk_profile = st.sidebar.selectbox(":בחר את רמת הסיכון", ["(Aggressive (אגרסיבי", "(Moderate (מאוזן ", "(Conservative (סולידי"], index=1)
investment_amount = st.sidebar.number_input("(($) סכום הגדרת בסיס:", min_value=100, value=int(user_db["cash"]), step=500)
risk_percent = st.sidebar.slider(":(%) אחוז סיכון מקסימלי", min_value=0.5, max_value=5.0, value=2.0, step=0.5)
ticker_1 = st.sidebar.text_input("🔍 בחירת מניה לסריקה ומסחר", value="AAPL").upper().strip()

end_date = datetime.today()
start_date = end_date - timedelta(days=365 * 2)
def load_stock_data(ticker_symbol, start, end):
    if not ticker_symbol: return pd.DataFrame(), None
    try:
        stock_obj = yf.Ticker(ticker_symbol)
        return stock_obj.history(start=start, end=end, auto_adjust=True), stock_obj
    except: return pd.DataFrame(), None

def get_dividend_info(stock_obj):
    div_info = {"ex_date": "אין נתונים", "pay_date": "אין נתונים", "amount": 0.0}
    if stock_obj is None: return div_info
    try:
        calendar = stock_obj.calendar
        if calendar is not None and not calendar.empty:
            if 'Dividend Date' in calendar.index: div_info["pay_date"] = calendar.loc['Dividend Date'].values.strftime('%Y-%m-%d')
            if 'Ex-Dividend Date' in calendar.index: div_info["ex_date"] = calendar.loc['Ex-Dividend Date'].values.strftime('%Y-%m-%d')
        div_info["amount"] = stock_obj.info.get("dividendRate", 0.0) or 0.0
    except: pass
    return div_info

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
                st.toast(f"פקודת קנייה עתידית בוצעה עבור {tick}!")
        elif o_type == "SELL_LIMIT" and curr_price >= target:
            if data["portfolio"].get(tick, 0) >= qty:
                data["cash"] += curr_price * qty
                data["portfolio"][tick] -= qty
                if data["portfolio"][tick] == 0: del data["portfolio"][tick]
                executed_any = True
                st.toast(f"פקודת מכירה עתידית בוצעה עבור {tick}!")
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

def analyze_ticker(df, info_dict, investment_amount, risk_percent, selected_risk_profile):
    df['MA200'] = df['Close'].rolling(window=200).mean()
    df['BB_Middle'] = df['Close'].rolling(window=20).mean()
    df['BB_Std'] = df['Close'].rolling(window=20).std()
    df['BB_Lower'] = df['BB_Middle'] - (2 * df['BB_Std'])
    
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['RSI'] = 100 - (100 / (1 + (gain / loss)))
    
    current_price = float(df['Close'].iloc[-1])
    current_rsi = df['RSI'].iloc[-1]
    ma200_curr = df['MA200'].iloc[-1]
    bb_lower_curr = df['BB_Lower'].iloc[-1]
    
    reasons = []
    score = 0
    if current_price > ma200_curr:
        score += 1
        reasons.append(f"המניה במגמה ראשית עולה (מעל ממוצע 200: ${ma200_curr:.2f}).")
    else:
        score -= 1
        reasons.append(f"המניה במגמת ירידה ארוכת טווח (מתחת לממוצע 200).")
        
    if current_price <= (bb_lower_curr * 1.02):
        score += 1
        reasons.append("המחיר קרוב לרצועת בולינגר התחתונה.")
        
    buy_threshold, sl_multiplier = (2, 0.98) if "סולידי" in selected_risk_profile else ((0, 0.94) if "אגרסיבי" in selected_risk_profile else (1, 0.96))
    verdict, v_type = ("הזדמנות קנייה (Buy)", "BUY") if score >= buy_threshold else (("להמתין לירידה (Wait)", "WAIT") if score < 0 else ("החזק / ניטרלי (Hold)", "HOLD"))
    stop_loss = bb_lower_curr * sl_multiplier
    
    return {"df": df, "verdict": verdict, "verdict_type": v_type, "current_price": current_price, "current_rsi": current_rsi, "waiting_target": bb_lower_curr, "stop_loss_price": stop_loss, "analysis_reasons": reasons}
# =========================================================
# חלק 4: חדר מסחר אישי, תצוגת נתונים ורענון (כל דקה)
# =========================================================

@st.fragment(run_every=60)
def render_realtime_simulator():
    global user_db
    # בדיקת פקודות עתידיות ספציפיות למשתמש זה
    if check_and_execute_user_orders(current_user, user_db):
        user_db = load_user_data(current_user)
        
    portfolio_val, holdings_distribution = calculate_portfolio_value(user_db["portfolio"])
    total_net_worth = user_db["cash"] + portfolio_val
    
    st.caption(f"🔄 עדכון נתונים אוטומטי של {current_user} פעיל (כל 60 שניות) | עדכון אחרון: {datetime.now().strftime('%H:%M:%S')}")
    
    col_w1, col_w2, col_w3 = st.columns(3)
    col_w1.metric("💵 מזומן פנוי במסחר", f"${user_db['cash']:,.2f}")
    col_w2.metric("📦 שווי מניות נוכחי", f"${portfolio_val:,.2f}")
    col_w3.metric("👑 שווי תיק כולל", f"${total_net_worth:,.2f}")
    
    if user_db.get("orders"):
        with st.expander("⏳ פקודות עתידיות ממתינות (Limit Orders)"):
            st.table(pd.DataFrame(user_db["orders"]))
            
    if user_db["portfolio"]:
        with st.expander("💼 פירוט החזקות נוכחי בתיק"):
            holding_data = [{"סימול": t, "כמות מניות": q, "שווי פוזיציה": f"${holdings_distribution.get(t, 0):,.2f}"} for t, q in user_db["portfolio"].items() if q > 0]
            st.table(pd.DataFrame(holding_data))

    if ticker_1:
        df1, stock_obj1 = load_stock_data(ticker_1, start_date, end_date)
        if df1.empty or len(df1) < 200:
            st.error(f"שגיאה בסימול {ticker_1}")
        else:
            res1 = analyze_ticker(df1, stock_obj1.info if stock_obj1 else {}, investment_amount, risk_percent, risk_profile)
            
            st.subheader(f"📅 לוח דיבידנדים למניית {ticker_1}")
            div_data = get_dividend_info(stock_obj1)
            cd1, cd2, cd3 = st.columns(3)
            cd1.metric("תשלום דיבידנד שנתי", f"${div_data['amount']:.2f}")
            cd2.metric("יום ה-X (Ex-Date)", div_data['ex_date'])
            cd3.metric("תאריך תשלום", div_data['pay_date'])
            
            st.subheader(f"🎛️ חדר מסחר וירטואלי של {current_user}: {ticker_1}")
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
                        user_db["orders"].append({"ticker": ticker_1, "type": "BUY_LIMIT", "target_price": target_price, "qty": trade_qty, "date": datetime.now().strftime('%m-%d %H:%M')})
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
                            user_db["orders"].append({"ticker": ticker_1, "type": "SELL_LIMIT", "target_price": target_price, "qty": trade_qty, "date": datetime.now().strftime('%m-%d %H:%M')})
                            save_user_data(current_user, user_db); st.rerun()

            with tc3:
                st.info(f" ברשותך **{user_shares}** מניות בשווי **${user_shares * curr_stock_price:,.2f}**.\n\n מחיר שוק: **${curr_stock_price:.2f}**")

            # --- דוח ניתוח והמלצות ---
            st.markdown("---")
            st.subheader(f"📊 דוח ניתוח ממוקד ומחשבון סיכונים: {ticker_1}")
            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric("סטטוס מערכת", res1['verdict'])
            col_m2.metric("מדד RSI", f"{res1['current_rsi']:.1f}")
            col_m3.metric("קטיעת הפסד מומלצת (SL)", f"${res1['stop_loss_price']:.2f}")
            
            for r in res1['analysis_reasons']: st.write(f"• {r}")
            
            # --- גרף טכני ---
            df = res1['df']
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06, row_heights=[0.7, 0.3])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close']), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['BB_Middle'], line=dict(color='cyan', width=1)), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='purple', width=1.2)), row=2, col=1)
            fig.update_layout(xaxis_rangeslider_visible=False, template="plotly_dark", height=350, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

render_realtime_simulator()
