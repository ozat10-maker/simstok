import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timedelta

# =========================================================
# חלק 1: הגדרות דף ותשתית בסיס הנתונים (JSON)
# =========================================================
st.set_page_config(page_title="סימולטור השקעות מתקדם", layout="wide")
st.title("📈 סימולטור השקעות ומנוע מסחר בזמן אמת")
st.write("המערכת מתעדכנת אוטומטית בכל דקה, שומרת פקודות עתידיות, מציגה דיבידנדים ומנהלת ארנק קבוע.")
st.markdown("---")

DB_FILE = "portfolio_db.json"

def load_database():
    """טעינת הנתונים מהקובץ הקבוע בשרת"""
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {"cash": 10000.0, "portfolio": {}, "orders": []}

def save_database(data):
    """שמירת המצב הנוכחי לקובץ קבוע"""
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)

# אתחול הנתונים בקריאה ראשונה
if 'db' not in st.session_state:
    st.session_state['db'] = load_database()

db = st.session_state['db']

# --- (Sidebar) סרגל צדי ---
st.sidebar.header("👤 פרופיל משקיע ורמת סיכון")
risk_profile = st.sidebar.selectbox(
    ":בחר את רמת הסיכון המתאימה לך", 
    ["(Aggressive (אגרסיבי", "(Moderate (מאוזן ", "(Conservative (סולידי"], 
    index=1
)
st.sidebar.markdown("---")

st.sidebar.header("💰 הגדרות תקציב וסיכונים")
investment_amount = st.sidebar.number_input("(($) סכום הגדרת בסיס:", min_value=100, value=int(db["cash"]), step=500)
risk_percent = st.sidebar.slider(":(%) אחוז סיכון מקסימלי מהתיק", min_value=0.5, max_value=5.0, value=2.0, step=0.5)
st.sidebar.markdown("---")

if st.sidebar.button("🔄 איפוס מלא של התיק והפקודות"):
    db = {"cash": 10000.0, "portfolio": {}, "orders": []}
    save_database(db)
    st.session_state['db'] = db
    st.rerun()

st.sidebar.header("🔍 בחירת מניה לסריקה ומסחר")
ticker_1 = st.sidebar.text_input(":(חובה) מניה ראשונה", value="AAPL").upper().strip()
st.sidebar.markdown("---")

end_date = datetime.today()
start_date = end_date - timedelta(days=365 * 2)

def load_stock_data(ticker_symbol, start, end):
    if not ticker_symbol:
        return pd.DataFrame(), {}
    try:
        stock_obj = yf.Ticker(ticker_symbol)
        hist_df = stock_obj.history(start=start, end=end, auto_adjust=True)
        return hist_df, stock_obj
    except:
        return pd.DataFrame(), None
def get_dividend_info(stock_obj):
    """שליפת מידע על יום ה-X ותאריך התשלום הקרוב של הדיבידנד"""
    div_info = {"ex_date": "אין נתונים", "pay_date": "אין נתונים", "amount": 0.0}
    if stock_obj is None:
        return div_info
    try:
        calendar = stock_obj.calendar
        if calendar is not None and not calendar.empty:
            if 'Dividend Date' in calendar.index:
                div_info["pay_date"] = calendar.loc['Dividend Date'].values.strftime('%Y-%m-%d')
            if 'Ex-Dividend Date' in calendar.index:
                div_info["ex_date"] = calendar.loc['Ex-Dividend Date'].values.strftime('%Y-%m-%d')
        info = stock_obj.info
        div_info["amount"] = info.get("dividendRate", 0.0) if info.get("dividendRate") else 0.0
    except:
        pass
    return div_info

def check_and_execute_orders(db):
    """סריקה של הפקודות העתידיות וביצוען במידה והמחיר מתאים"""
    updated_orders = []
    executed_any = False
    
    for order in db.get("orders", []):
        tick = order["ticker"]
        target_price = order["target_price"]
        order_type = order["type"] 
        qty = order["qty"]
        
        df, _ = load_stock_data(tick, datetime.today() - timedelta(days=5), datetime.today())
        if df.empty:
            updated_orders.append(order)
            continue
            
        current_price = float(df['Close'].iloc[-1])
        
        if order_type == "BUY_LIMIT" and current_price <= target_price:
            cost = current_price * qty
            if db["cash"] >= cost:
                db["cash"] -= cost
                db["portfolio"][tick] = db["portfolio"].get(tick, 0) + qty
                executed_any = True
                st.toast(f"פקודת לימיט קנייה בוצעה! קנית {qty} מניות של {tick}")
            else:
                st.toast(f"נכשלה פקודת קנייה ב-{tick} עקב חוסר במזומן")
        elif order_type == "SELL_LIMIT" and current_price >= target_price:
            user_held = db["portfolio"].get(tick, 0)
            if user_held >= qty:
                db["cash"] += current_price * qty
                db["portfolio"][tick] -= qty
                if db["portfolio"][tick] == 0:
                    del db["portfolio"][tick]
                executed_any = True
                st.toast(f"פקודת לימיט מכירה בוצעה! מכרת {qty} מניות של {tick}")
        else:
            updated_orders.append(order)
            
    if executed_any:
        db["orders"] = updated_orders
        save_database(db)
        st.session_state['db'] = db
        return True
    return False

def calculate_portfolio_value(portfolio):
    total_val = 0.0
    shares_values = {}
    for tick, qty in portfolio.items():
        if qty <= 0:
            continue
        df, _ = load_stock_data(tick, datetime.today() - timedelta(days=5), datetime.today())
        if not df.empty:
            price = df['Close'].iloc[-1]
            current_value = float(price * qty)
            total_val += current_value
            shares_values[tick] = current_value
    return total_val, shares_values

def analyze_ticker(df, info_dict, investment_amount, risk_percent, ticker_name, portfolio_total_value, current_holding_value, selected_risk_profile):
    df['MA50'] = df['Close'].rolling(window=50).mean()
    df['MA200'] = df['Close'].rolling(window=200).mean()
    
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    df['BB_Middle'] = df['Close'].rolling(window=20).mean()
    df['BB_Std'] = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['BB_Middle'] + (2 * df['BB_Std'])
    df['BB_Lower'] = df['BB_Middle'] - (2 * df['BB_Std'])
    
    current_price = float(df['Close'].iloc[-1])
    current_rsi = df['RSI'].iloc[-1]
    ma200_curr = df['MA200'].iloc[-1]
    bb_lower_curr = df['BB_Lower'].iloc[-1]
    bb_upper_curr = df['BB_Upper'].iloc[-1]
    
    analysis_reasons = []
    score = 0
    
    if current_price > ma200_curr:
        score += 1
        analysis_reasons.append(f"המניה במגמה ראשית עולה (מעל ממוצע נע 200 השוכן ב- ${ma200_curr:.2f}).")
    else:
        score -= 1
        analysis_reasons.append(f"המניה במגמת ירידה ארוכת טווח (מתחת לממוצע נע 200 השוכן ב- ${ma200_curr:.2f}).")
        
    candle_pattern_detected = "אין תבנית מיוחדת"
    if current_price <= (bb_lower_curr * 1.02):
        score += 1
        analysis_reasons.append(f"המחיר קרוב לרצועת בולינגר התחתונה (${bb_lower_curr:.2f}).")
        
    if "סולידי" in selected_risk_profile:
        buy_threshold, sl_multiplier = 2, 0.98
    elif "אגרסיבי" in selected_risk_profile:
        buy_threshold, sl_multiplier = 0, 0.94
    else:
        buy_threshold, sl_multiplier = 1, 0.96
        
    if score >= buy_threshold:
        verdict, verdict_type = "הזדמנות קנייה (Buy)", "BUY"
    elif score < 0:
        verdict, verdict_type = "להמתין לירידה (Wait)", "WAIT"
    else:
        verdict, verdict_type = "החזק / ניטרלי (Hold)", "HOLD"
        
    waiting_target = bb_lower_curr if pd.notna(bb_lower_curr) else current_price * 0.95
    stop_loss_price = waiting_target * sl_multiplier
    
    return {
        "df": df, "verdict": verdict, "verdict_type": verdict_type,
        "current_price": current_price, "current_rsi": current_rsi, "waiting_target": waiting_target,
        "stop_loss_price": stop_loss_price, "analysis_reasons": analysis_reasons, "candle_pattern": candle_pattern_detected
    }
# =========================================================
# חלק 3: ממשק המשתמש ומערכת הרענון האוטומטי (כל דקה)
# =========================================================

@st.fragment(run_every=60)
def render_realtime_simulator():
    global db
    if check_and_execute_orders(db):
        db = load_database()
        
    portfolio_val, holdings_distribution = calculate_portfolio_value(db["portfolio"])
    total_net_worth = db["cash"] + portfolio_val
    
    st.caption(f"🔄 עדכון נתונים אוטומטי פעיל (כל 60 שניות) | זמן עדכון אחרון: {datetime.now().strftime('%H:%M:%S')}")
    
    col_wallet1, col_wallet2, col_wallet3 = st.columns(3)
    col_wallet1.metric("💵 מזומן פנוי במסחר", f"${db['cash']:,.2f}")
    col_wallet2.metric("📦 שווי מניות נוכחי", f"${portfolio_val:,.2f}")
    col_wallet3.metric("👑 שווי תיק כולל (Net Worth)", f"${total_net_worth:,.2f}")
    
    if db.get("orders"):
        with st.expander("⏳ פקודות עתידיות ממתינות (Limit Orders)"):
            st.table(pd.DataFrame(db["orders"]))
            
    if db["portfolio"]:
        with st.expander("💼 פירוט החזקות נוכחי בתיק"):
            holding_data = []
            for tick, qty in db["portfolio"].items():
                if qty > 0:
                    holding_data.append({"סימול": tick, "כמות מניות": qty, "שווי פוזיציה": f"${holdings_distribution.get(tick, 0):,.2f}"})
            st.table(pd.DataFrame(holding_data))

    if not ticker_1:
        st.warning("אנא הזן סימול מניה בשדה החובה בסרגל הצדי.")
    else:
        df1, stock_obj1 = load_stock_data(ticker_1, start_date, end_date)
        
        if df1.empty or len(df1) < 200:
            st.error(f"שגיאה: סימול המניה {ticker_1} אינו תקין או שאין מספיק נתונים.")
        else:
            info_dict = stock_obj1.info if stock_obj1 else {}
            val_held_1 = holdings_distribution.get(ticker_1, 0.0)
            res1 = analyze_ticker(df1, info_dict, investment_amount, risk_percent, ticker_1, portfolio_val, val_held_1, risk_profile)
            
            st.subheader(f"📅 לוח דיבידנדים ומסחרי למניית {ticker_1}")
            div_data = get_dividend_info(stock_obj1)
            
            c_div1, c_div2, c_div3 = st.columns(3)
            c_div1.metric("תשלום דיבידנד שנתי", f"${div_data['amount']:.2f}")
            c_div2.metric("יום ה-X הקרוב (Ex-Date)", div_data['ex_date'])
            c_div3.metric("תאריך תשלום פיזי", div_data['pay_date'])
            
            st.subheader(f"🎛️ חדר מסחר וירטואלי: {ticker_1}")
            trade_col1, trade_col2, trade_col3 = st.columns(3)
            
            current_stock_price = res1['current_price']
            user_shares_held = db["portfolio"].get(ticker_1, 0.0)
            with trade_col1:
                trade_qty = st.number_input("כמות מניות לפעולה:", min_value=1, value=10, step=1)
                action_mode = st.radio("סוג פעולה:", ["ביצוע מיידי (Market)", "פקודה עתידית (Limit)"])
                
                target_price = current_stock_price
                if action_mode == "פקודה עתידית (Limit)":
                    target_price = st.number_input("מחיר יעד להפעלה ($):", min_value=0.01, value=current_stock_price, step=0.5)
                    
            with trade_col2:
                st.write("")
                st.write("")
                if st.button("🟢 שלח פקודת קנייה", use_container_width=True):
                    if action_mode == "ביצוע מיידי (Market)":
                        cost = trade_qty * current_stock_price
                        if db["cash"] >= cost:
                            db["cash"] -= cost
                            db["portfolio"][ticker_1] = db["portfolio"].get(ticker_1, 0.0) + trade_qty
                            save_database(db)
                            st.success(f"קנית {trade_qty} מניות של {ticker_1}")
                            st.rerun()
                        else:
                            st.error("אין מספיק מזומן פנוי.")
                    else:
                        db["orders"].append({"ticker": ticker_1, "type": "BUY_LIMIT", "target_price": target_price, "qty": trade_qty, "date": datetime.now().strftime('%Y-%m-%d %H:%M')})
                        save_database(db)
                        st.info(f"פקודת לימיט הוכנסה למערכת.")
                        st.rerun()
                        
                if st.button("🔴 שלח פקודת מכירה", use_container_width=True):
                    if action_mode == "ביצוע מיידי (Market)":
                        if user_shares_held >= trade_qty:
                            db["cash"] += trade_qty * current_stock_price
                            db["portfolio"][ticker_1] -= trade_qty
                            if db["portfolio"][ticker_1] == 0:
                                del db["portfolio"][ticker_1]
                            save_database(db)
                            st.success(f"מכרת {trade_qty} מניות.")
                            st.rerun()
                        else:
                            st.error("אין לך מספיק מניות.")
                    else:
                        if user_shares_held >= trade_qty:
                            db["orders"].append({"ticker": ticker_1, "type": "SELL_LIMIT", "target_price": target_price, "qty": trade_qty, "date": datetime.now().strftime('%Y-%m-%d %H:%M')})
                            save_database(db)
                            st.info(f"פקודת לימיט הוכנסה למערכת.")
                            st.rerun()
                        else:
                            st.error("אין ברשותך מספיק מניות.")

            with trade_col3:
                st.info(f"ℹ️ **סטטוס החזקה במניית {ticker_1}:** \n\n ברשותך כרגע **{user_shares_held}** מניות בשווי שוק של **${user_shares_held * current_stock_price:,.2f}**.\n\n מחיר שוק נוכחי: **${current_stock_price:.2f}**")

            st.markdown("---")
            st.subheader(f"📊 דוח ניתוח ממוקד: {info_dict.get('longName', ticker_1)} ({ticker_1})")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("מחיר נוכחי", f"${res1['current_price']:.2f}")
            c2.metric("מדד RSI", f"{res1['current_rsi']:.1f}")
            c3.metric("תבנית נר שזוהתה", res1['candle_pattern'])
            c4.metric("סטטוס מערכת", res1['verdict'])

            st.write("### 🧠 סיכום תהליך הניתוח והממצאים הטכניים")
            st.write(f"הדוח מותאם אישית עבור פרופיל משקיע: **{risk_profile}**")
            for reason in res1['analysis_reasons']: 
                st.write(f" {reason}")

            st.markdown("---")
            st.subheader("🛡️ מחשבון ניהול סיכונים והנחיות פעולה לתקציב") 
            
            allowed_loss_usd = investment_amount * (risk_percent / 100)
            risk_per_share = current_stock_price - res1['stop_loss_price']
            if risk_per_share <= 0: risk_per_share = current_stock_price * 0.05
            total_shares = int(allowed_loss_usd / risk_per_share)
            if (total_shares * current_stock_price) > investment_amount:
                total_shares = int(investment_amount / current_stock_price)
            s_p1 = int(total_shares * 0.60)
            s_p2 = total_shares - s_p1

            col1, col2, col3 = st.columns(3)
            if res1['verdict_type'] == "WAIT":
                col1.metric("סך מניות לקנייה מיידית", "0 יחידות")
                col2.metric("תקציב מנוצל כרגע", "$0.00")
                col3.metric("מחיר קטיעת הפסד (Stop Loss)", f"${res1['stop_loss_price']:.2f}")
                st.error(f"**אסטרטגיית פעולה ל-{ticker_1} (להמתין לירידה):**") 
                st.markdown(f"* **אין לבצע קנייה במחיר השוק הנוכחי (${current_stock_price:.2f}).**\n* **פקודת לימיט עתידית:** מומלץ למקם פקודת רכש עבור **{total_shares}** יחידות ברמת התמיכה/בולינגר תחתון ב-**${res1['waiting_target']:.2f}**.")
            elif res1['verdict_type'] == "HOLD":
                col1.metric("סך מניות מומלץ", f"{s_p1} יחידות")
                col2.metric("תקציב מנוצל ראשוני", f"${s_p1 * current_stock_price:,.2f}")
                col3.metric("מחיר קטיעת הפסד (Stop Loss)", f"${res1['stop_loss_price']:.2f}")
                st.warning(f"**אסטרטגיית פעולה ל-{ticker_1} (מצב ניטרלי/דשדוש):**") 
                st.markdown(f"* **שלב א':** קנה רק **{s_p1}** יחידות במחיר הנוכחי (**${current_stock_price:.2f}**).\n* **שלב ב': שים פקודת לימיט ל**-**{s_p2}** יחידות בקו התמיכה (**${res1['waiting_target']:.2f}**).")
            else: 
                col1.metric("סך מניות מומלץ לקנייה", f"{total_shares} יחידות")
                col2.metric("תקציב מנוצל בפועל", f"${(s_p1 * current_stock_price) + (s_p2 * res1['waiting_target']):,.2f}")
                col3.metric("מחיר קטיעת הפסד (Stop Loss)", f"${res1['stop_loss_price']:.2f}")
                st.success(f"**אסטרטגיית פעולה ל-{ticker_1} (אות קנייה):**") 
                st.markdown(f"* **שלב א' (כניסה מיידית):** קנה **{s_p1}** מניות במחיר נוכחי (**${current_stock_price:.2f}**).\n* **שלב ב' (חיזוק בתמיכה):** הצב פקודת לימיט ל-**{s_p2}** מניות בשער **${res1['waiting_target']:.2f}**.")

            st.markdown("---")
            df = res1['df']
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06, row_heights=[0.7, 0.3])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close']), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['BB_Upper'], line=dict(color='rgba(173,216,230,0.4)', width=1, dash='dash'), name="בולינגר עליון"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['BB_Lower'], line=dict(color='rgba(173,216,230,0.4)', width=1, dash='dash'), name="בולינגר תחתון"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['BB_Middle'], line=dict(color='cyan', width=1), name="בולינגר אמצע"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['MA200'], line=dict(color='red', width=1.2)), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='purple', width=1.2)), row=2, col=1)
            fig.update_layout(xaxis_rangeslider_visible=False, template="plotly_dark", height=400, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

render_realtime_simulator()
