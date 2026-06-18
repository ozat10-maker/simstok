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
# חלק 1: הגדרות דף, בסיס נתונים SQLite משודרג (גרסה 14)
# =========================================================
st.set_page_config(page_title="סימולטור השקעות מקצועי מקצה לקצה", layout="wide")

DB_FILE = "/tmp/simulator_pro_v14.db" 
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
    # טבלת היסטוריית שווי תיק לאורך זמן (עבור הגרף הקווי)
    c.execute('''CREATE TABLE IF NOT EXISTS portfolio_history 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, timestamp TEXT, net_worth_ils REAL)''')
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
def log_portfolio_worth(username, net_worth_ils):
    """תיעוד שווי התיק הנוכחי בבסיס הנתונים לצורך הפקת גרף ביצועים קווי"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("INSERT INTO portfolio_history (username, timestamp, net_worth_ils) VALUES (?, ?, ?)", (username, now_str, net_worth_ils))
    conn.commit()
    conn.close()

def load_portfolio_worth_history(username):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT timestamp as 'זמן', net_worth_ils as 'שווי תיק (₪)' FROM portfolio_history WHERE username=? ORDER BY id ASC", conn, params=(username,))
    conn.close()
    return df

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

def get_usd_ils_rate():
    try:
        df = yf.Ticker("USDILS=X").history(period="1d")
        if not df.empty and pd.notna(df['Close'].iloc[-1]): return float(df['Close'].iloc[-1])
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
            if close_today is None or pd.isna(close_today): close_today = df['Close'].iloc[-1] if not df.empty else 0.0
            close_yesterday = df['Close'].iloc[-2] if len(df) >= 2 else close_today
            if ".TA" in ticker:  
                close_today /= 100
                close_yesterday /= 100
            pct_change = ((close_today - close_yesterday) / close_yesterday) * 100 if close_yesterday > 0 else 0.0
            cols[i].metric(name, f"${close_today:,.2f}" if "$" in name or "Bitcoin" in name else f"₪{close_today:,.2f}", f"{pct_change:+.2f}%")
        except: cols[i].metric(name, "טוען...")

st.title("📈 פלטפורמת מסחר וסיมולציה מקצועית")
render_top_market_indices()
st.markdown("---")

if 'logged_in_user' not in st.session_state: st.session_state['logged_in_user'] = None

if st.session_state['logged_in_user'] is None:
    st.subheader("🔐 התחברות מאובטחת לניהול תיק אישי")
    auth_tab1, auth_tab2 = st.tabs(["🔑 התחברות משתמש", "📝 פתיחת חשבון חדש"])
    with auth_tab1:
        login_user_input = st.text_input("שם משתמש:", key="login_user").strip()
        login_pass_input = st.text_input("סיסמה:", type="password", key="login_pass").strip()
        if st.button("התחבר למערכת", use_container_width=True):
            if login_user_input and login_pass_input and login_user(login_user_input, login_pass_input):
                st.session_state['logged_in_user'] = login_user_input
                st.success(f"ברוך הבא {login_user_input}.")
                st.rerun()
            else: st.error("שם משתמש או סיסמה שגויים.")
    with auth_tab2:
        reg_user_input = st.text_input("בחר שם משתמש:", key="reg_user").strip()
        reg_pass_input = st.text_input("בחר סיסמה:", type="password", key="reg_pass").strip()
        if st.button("צור חשבון סימולציה חדש", use_container_width=True):
            if reg_user_input and reg_pass_input and register_user(reg_user_input, reg_pass_input): 
                st.success("החשבון נוצר! בצע התחברות כעת.")
            else: st.error("שם המשתמש תפוס או שגוי.")
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
init_db()
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
        return f"{(diff.seconds % 3600) // 60} דקות"
    except: return "N/A"

def check_and_execute_limit_orders(username, data, ex_rate):
    """סריקה וביצוע אוטומטי של פקודות עתידיות (Limit) ברקע לפי מחירי השוק הנוכחיים"""
    updated_orders = []
    executed_any = False
    
    for order in data.get("orders", []):
        tick, target, o_type, qty = order["ticker"], order["target_price"], order["type"], order["qty"]
        df, obj = load_stock_data(tick)
        price_raw = get_safe_current_price(obj, df)
        if price_raw == 0:
            updated_orders.append(order)
            continue
            
        curr_price = price_raw / 100 if ".TA" in tick else price_raw
        is_ta = ".TA" in tick
        gross_ils = qty * curr_price * (1.0 if is_ta else ex_rate)
        comm_ils = gross_ils * COMMISSION_RATE
        
        if o_type == "BUY_LIMIT" and curr_price <= target:
            if data["cash_ils"] >= (gross_ils + comm_ils):
                data["cash_ils"] -= (gross_ils + comm_ils)
                h_info = data["portfolio"].get(tick, {"qty": 0, "avg_price_source": 0.0, "first_buy_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
                new_qty = h_info["qty"] + qty
                new_avg = ((h_info["qty"] * h_info["avg_price_source"]) + (qty * curr_price)) / new_qty if h_info["qty"] > 0 else curr_price
                data["portfolio"][tick] = {"qty": new_qty, "avg_price_source": new_avg, "first_buy_time": h_info.get("first_buy_time", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}
                add_to_history(username, tick, "BUY (LIMIT)", qty, curr_price, (1.0 if is_ta else ex_rate), comm_ils, 0.0, (gross_ils + comm_ils))
                executed_any = True
                st.toast(f"🎯 פקודת לימיט קנייה בוצעה בהצלחה עבור {tick}!")
            else: updated_orders.append(order)
        elif o_type == "SELL_LIMIT" and curr_price >= target:
            h_info = data["portfolio"].get(tick, {"qty": 0, "avg_price_source": 0.0})
            if h_info["qty"] >= qty:
                profit_source = (curr_price - h_info["avg_price_source"]) * qty
                tax_ils = (profit_source * (1.0 if is_ta else ex_rate) * TAX_RATE) if profit_source > 0 else 0.0
                total_rec_ils = gross_ils - comm_ils - tax_ils
                data["cash_ils"] += total_rec_ils
                data["portfolio"][tick]["qty"] -= qty
                if data["portfolio"][tick]["qty"] == 0: del data["portfolio"][tick]
                add_to_history(username, tick, "SELL (LIMIT)", qty, curr_price, (1.0 if is_ta else ex_rate), comm_ils, tax_ils, total_rec_ils)
                executed_any = True
                st.toast(f"🎯 פקודת לימיט מכירה בוצעה בהצלחה עבור {tick}!")
            else: del order # מניות כבר לא קיימות
        else: updated_orders.append(order)
        
    if executed_any:
        data["orders"] = updated_orders
        save_user_data(username, data)
        return True
    return False

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
        if price_raw == 0: price_raw = info.get("avg_price_source", 1.0) * (100 if ".TA" in tick else 1.0)
        price_converted = price_raw / 100 if ".TA" in tick else price_raw
        val_ils = price_converted * qty * (1.0 if ".TA" in tick else ex_rate)
        total_val_ils += val_ils
        shares_data[tick] = {"val_ils": val_ils, "price_source_currency": price_converted}
    return total_val_ils, shares_data

def analyze_ticker(df, selected_risk_profile, is_ils_stock, stock_obj):
    df['MA200'] = df['Close'].rolling(window=200).mean()
    df['BB_Middle'] = df['Close'].rolling(window=20).mean()
    df['BB_Std'] = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['BB_Middle'] + (2 * df['BB_Std'])
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
    buy_threshold, sl_multiplier = (2, 0.98) if "סולידי" in selected_risk_profile else ((0, 0.94) if "אגרסיבי" in selected_risk_profile else (1, 0.96))
    verdict, v_type = ("הזדמנות קנייה (Buy)", "BUY") if score >= buy_threshold else (("להמתין לירידה (Wait)", "WAIT") if score < 0 else ("החזק / ניטרלי (Hold)", "HOLD"))
    return {"df": df, "verdict": verdict, "verdict_type": v_type, "current_price": current_price, "waiting_target": bb_lower_curr, "stop_loss_price": bb_lower_curr * sl_multiplier, "analysis_reasons": reasons}
@st.fragment(run_every=60)
def render_realtime_simulator():
    global user_db, usd_ils, ticker_1
    
    # בדיקת פקודות עתידיות ברקע כל דקה
    if check_and_execute_limit_orders(current_user, user_db, usd_ils):
        user_db = load_user_data(current_user)
        
    portfolio_val_ils, holdings_dist = calculate_portfolio_value_ils(user_db["portfolio"], usd_ils)
    if pd.isna(portfolio_val_ils): portfolio_val_ils = 0.0
    total_net_worth_ils = user_db["cash_ils"] + portfolio_val_ils
    
    # תיעוד היסטוריית שווי התיק בבסיס הנתונים
    log_portfolio_worth(current_user, total_net_worth_ils)
    
    tab_portfolio, tab_trade, tab_history = st.tabs([
        "💼 תיק ההשקעות ופילוח נכסים", 
        "🔍 חדר מסחר ואנליזת מניות", 
        "📜 יומן פעולות ורשימת מעקב"
    ])
    
    # -----------------------------------------------------
    # לשונית 1: תיק ההשקעות שלי + עמודת שווי פוזיציה + גרף קווי + מדליות
    # -----------------------------------------------------
    with tab_portfolio:
        st.subheader("📊 מצב כספי וסיכום יתרות")
        cw1, cw2, cw3 = st.columns(3)
        cw1.metric("💵 מזומן פנוי (ILS)", f"₪{user_db['cash_ils']:,.2f}")
        cw2.metric("📦 שווי מניות (ILS)", f"₪{portfolio_val_ils:,.2f}")
        cw3.metric("👑 שווי תיק כולל (Net Worth)", f"₪{total_net_worth_ils:,.2f}")
        
        st.markdown("---")
        st.subheader("📦 פוזיציות פתוחות בתיק")
        holding_rows = []
        pie_labels, pie_values = ["מזומן פנוי (Cash)"], [user_db["cash_ils"]]
        has_us, has_il, has_multi_sector = False, False, set()
        
        if user_db.get("portfolio"):
            for tick, info in user_db["portfolio"].items():
                qty = info.get("qty", 0)
                if qty <= 0: continue
                if ".TA" in tick: has_il = True
                else: has_us = True
                
                df, obj = load_stock_data(tick)
                price_raw = get_safe_current_price(obj, df)
                daily_chg = get_daily_change_pct(obj, df)
                is_ta_asset = ".TA" in tick
                
                if price_raw == 0:
                    price_raw = info.get("avg_price_source", 1.0)
                    if is_ta_asset: price_raw *= 100
                    
                curr_market_price = price_raw / 100 if is_ta_asset else price_raw
                asset_val_ils = curr_market_price * qty * (1.0 if is_ta_asset else usd_ils)
                currency_sym = "₪" if is_ta_asset else "$"
                
                # שדרוג מבוקש: חישוב שווי פוזיציה מעודכן (מחיר שוק X כמות מניות) במטבע המקור
                current_position_value_source = curr_market_price * qty
                
                pie_labels.append(tick)
                pie_values.append(asset_val_ils)
                if obj: has_multi_sector.add(obj.info.get('sector', 'Other'))
                
                avg_buy_cost = info.get("avg_price_source", 0.0)
                roi_pct = ((curr_market_price - avg_buy_cost) / avg_buy_cost) * 100 if avg_buy_cost > 0 else 0.0
                time_string = calculate_time_elapsed(info.get("first_buy_time", datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                
                holding_rows.append({
                    "סימול מניה": tick,
                    "כמות יחידות": f"{qty:,.0f}",
                    "עלות קנייה (ליחידה)": f"{currency_sym}{avg_buy_cost:,.2f}",
                    "מחיר שוק נוכחי": f"{currency_sym}{curr_market_price:,.2f}",
                    "שווי פוזיציה עדכני": f"{currency_sym}{current_position_value_source:,.2f}", # תצוגת הפיתוח המשודרג
                    "שינוי יומי": f"{daily_chg:+.2f}%",     
                    "תשואה מצטברת (ROI)": f"{roi_pct:+.2f}%", 
                    "זמן פוזיציה": time_string
                })
                    
        if holding_rows:
            st.dataframe(pd.DataFrame(holding_rows).set_index("סימול מניה"), use_container_width=True)
            
            # תצוגת הגרפים (עוגה פלוס קווי לאורך זמן)
            g1, g2 = st.columns(2)
            with g1:
                st.subheader("🍩 פילוח ויזואלי של נכסי התיק")
                fig_pie = go.Figure(data=[go.Pie(labels=pie_labels, values=pie_values, hole=.4, textinfo='label+percent')])
                fig_pie.update_layout(template="plotly_dark", height=300, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig_pie, use_container_width=True)
            with g2:
                st.subheader("📊 עקומת צמיחת שווי התיק לאורך זמן")
                history_df = load_portfolio_worth_history(current_user)
                if not history_df.empty:
                    fig_line = go.Figure(data=[go.Scatter(x=history_df['זמן'], y=history_df['שווי תיק (₪)'], mode='lines+markers', line=dict(color='emerald', width=2))])
                    fig_line.update_layout(template="plotly_dark", height=300, margin=dict(l=10, r=10, t=10, b=10))
                    st.plotly_chart(fig_line, use_container_width=True)
        else: st.info("אין כרגע מניות בתיק.")
        
        # פאנל הישגים וגביעים (Gamification)
        st.markdown("---")
        st.subheader("🏆 הישגים וגביעי מסחר וירטואליים")
        ac1, ac2, ac3 = st.columns(3)
        ac1.markdown(f"🌍 **המשקיע הגלובלי:** {'🥇 הושג (מחזיק מניות בארץ ובחו\"ל)' if has_us and has_il else '🔒 נעול (קנה מניה אמריקאית וישראלית)'}")
        ac2.markdown(f"🛡️ **מנהל סיכונים:** {'🥇 הושג (פיזור ב-3 סקטורים)' if len(has_multi_sector) >= 3 else '🔒 נעול (פזר השקעות ב-3 סקטורים שונים)'}")
        ac3.markdown(f"💰 **מועדון המאה:** {'🥇 הושג (שווי תיק מעל 110,000 ₪)' if total_net_worth_ils > 110000 else '🔒 נעול (הגע לשווי תיק של 110k ₪)'}")

    # -----------------------------------------------------
    # לשונית 2: חדר מסחר ואנליזת מניות (תמיכה מלאה בפקודות לימיט)
    # -----------------------------------------------------
    with tab_trade:
        if ticker_1:
            df1, stock_obj1 = load_stock_data(ticker_1)
            if not df1.empty and stock_obj1 and len(df1) > 20:
                is_ta = ".TA" in ticker_1
                res1 = analyze_ticker(df1, risk_profile, is_ta, stock_obj1)
                curr_price_normalized = res1['current_price']
                
                st.subheader(f"🎛️ פאנל ביצוע עסקאות מיידיות ועתידיות עבור: {ticker_1}")
                tc1, tc2, tc3 = st.columns(3)
                holding_info = user_db["portfolio"].get(ticker_1, {"qty": 0, "avg_price_source": 0.0, "first_buy_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
                
                with tc1:
                    t_qty = st.number_input("כמות יחידות לביצוע:", min_value=1, value=10, step=1, key="trade_qty_input")
                    action_mode = st.radio("סוג הוראת מסחר:", ["ביצוע מיידי (Market)", "פקודה עתידית (Limit)"])
                    target_price = st.number_input("מחיר יעד להפעלה ($ או ₪):", min_value=0.01, value=curr_price_normalized, step=0.5) if action_mode == "פקודה עתידית (Limit)" else curr_price_normalized
                
                with tc2:
                    st.write(""); st.write("")
                    gross_cost_ils = t_qty * curr_price_normalized * (1.0 if is_ta else usd_ils)
                    commission_ils = gross_cost_ils * COMMISSION_RATE
                    
                    if st.button("🟢 שלח פקודת קנייה", use_container_width=True, key="buy_btn"):
                        if action_mode == "ביצוע מיידי (Market)":
                            total_charge_ils = gross_cost_ils + commission_ils
                            if user_db["cash_ils"] >= total_charge_ils:
                                user_db["cash_ils"] -= total_charge_ils
                                old_qty = holding_info["qty"]
                                new_qty = old_qty + t_qty
                                weighted_avg_price = ((old_qty * holding_info["avg_price_source"]) + (t_qty * curr_price_
