import streamlit as st
import pandas as pd
import datetime
import google.generativeai as genai

st.set_page_config(page_title="飲食熱量記錄系統", page_icon="🔥", layout="wide")

# -----------------------------------------------------------------------------
# 1. 系統安全：密碼鎖機制
# -----------------------------------------------------------------------------
def check_password():
    """驗證使用者密碼是否正確"""
    def password_entered():
        # 核對輸入的密碼是否與 secrets 中的密碼相符
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # 驗證成功後清除輸入框內的密碼紀錄
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # 第一次進入，顯示密碼輸入框
        st.title("🔒 系統已鎖定")
        st.text_input("請輸入專屬密碼以解鎖系統：", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        # 密碼錯誤，顯示錯誤提示
        st.title("🔒 系統已鎖定")
        st.text_input("請輸入專屬密碼以解鎖系統：", type="password", on_change=password_entered, key="password")
        st.error("😕 密碼錯誤，請再試一次。")
        return False
    else:
        # 密碼正確，放行
        return True

# 如果密碼驗證未通過，就停止執行後續的所有程式碼
if not check_password():
    st.stop()

# ==========================================
# (原本的程式碼從這裡開始繼續放...)
# 初始化 Session State 等邏輯
# ==========================================
# -----------------------------------------------------------------------------
# 系統初始化與狀態管理
# -----------------------------------------------------------------------------
st.set_page_config(page_title="飲食熱量記錄系統", page_icon="🔥", layout="wide")

# 初始化 Session State
if 'water_intake' not in st.session_state:
    st.session_state.water_intake = 0
if 'total_calories' not in st.session_state:
    st.session_state.total_calories = 0

# 計算第 X 天 (起始日 2026/01/13)
start_date = datetime.date(2026, 1, 13)
today = datetime.date.today()
day_count = (today - start_date).days + 1

# -----------------------------------------------------------------------------
# 側邊欄：用戶資訊與目標設定
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("👤 用戶資訊")
    st.write(f"📅 **今天是第 {day_count} 天**")

    # 基本資料輸入 (預設數值已配置)
    age = st.number_input("年齡", min_value=1, max_value=120, value=37, step=1)
    gender = st.selectbox("性別", options=["男", "女"])
    height = st.number_input("身高 (cm)", min_value=100.0, max_value=250.0, value=186.0, step=0.1)
    weight = st.number_input("體重 (kg)", min_value=30.0, max_value=200.0, value=95.0, step=0.1)

    activity_levels = {
        "久坐不動": 1.2,
        "輕度活動": 1.375,
        "中度活動": 1.55,
        "高度活動": 1.725,
        "極度活動": 1.9
    }
    activity = st.selectbox("活動量", options=list(activity_levels.keys()), index=0)

    # BMR 計算 (Harris-Benedict 公式)
    if gender == "男":
        bmr = 88.362 + (13.397 * weight) + (4.799 * height) - (5.677 * age)
    else:
        bmr = 447.593 + (9.247 * weight) + (3.098 * height) - (4.330 * age)

    tdee = bmr * activity_levels[activity]

    st.divider()
    st.subheader("🎯 每日目標")
    target_calories = st.number_input("目標熱量 (kcal)", value=int(tdee), step=100)

    # 營養素目標自動計算 (台灣衛福部標準)
    target_carbs = (target_calories * 0.55) / 4
    target_protein = weight * 1.0
    target_fat = (target_calories * 0.25) / 9
    target_sugar = (target_calories * 0.10) / 4
    target_water = 2000

    st.caption(f"基礎代謝率 (BMR): {bmr:.0f} kcal")
    st.caption(f"每日總消耗 (TDEE): {tdee:.0f} kcal")

# -----------------------------------------------------------------------------
# 主畫面：今日記錄與統計
# -----------------------------------------------------------------------------
st.title(f"今日飲食記錄 - {today.strftime('%Y/%m/%d')}")

# 三大板塊佈局
col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### 🔥 熱量攝取")
    st.progress(min(st.session_state.total_calories / target_calories, 1.0))
    st.write(f"**已攝取:** {st.session_state.total_calories} / {target_calories} kcal")
    st.write(f"**剩餘:** {max(target_calories - st.session_state.total_calories, 0)} kcal")

with col2:
    st.markdown("### 📊 營養素攝取統計")
    # 這裡放預設的進度條作為 UI 佔位符，後續與資料庫串接
    st.write(f"🍚 碳水: 0g / {target_carbs:.0f}g")
    st.progress(0.0)
    st.write(f"🥩 蛋白: 0g / {target_protein:.0f}g")
    st.progress(0.0)
    st.write(f"🥑 脂肪: 0g / {target_fat:.0f}g")
    st.progress(0.0)

with col3:
    st.markdown("### 💧 今日水分攝取")
    water_progress = min(st.session_state.water_intake / target_water, 1.0)
    st.progress(water_progress)
    st.write(f"**已飲用:** {st.session_state.water_intake} / {target_water} ml")

    if st.button("💧 +250ml", use_container_width=True):
        st.session_state.water_intake += 250
        st.rerun()

st.divider()

# -----------------------------------------------------------------------------
# 飲食記錄區塊與 API 串接預留
# -----------------------------------------------------------------------------
st.subheader("➕ 添加飲食記錄")
with st.expander("展開添加紀錄", expanded=True):
    meal_type = st.selectbox("用餐時間", ["早餐", "午餐", "晚餐", "點心"])
    food_name = st.text_input("食物名稱")
    food_weight = st.number_input("重量/份量 (克)", min_value=1, value=100)

    if st.button("🤖 使用 AI 查詢營養資訊"):
        # 這裡需要讀取 st.secrets["GEMINI_API_KEY"] 並進行 API 呼叫
        # 暫時以提示訊息代替
        if food_name:
            st.info(f"正在查詢 {food_name} ({food_weight}g) 的營養資訊... (API 串接準備中)")
        else:
            st.warning("請先輸入食物名稱")

st.divider()
st.subheader("🍽️ 用餐記錄列表")
st.caption("尚無紀錄... (資料庫串接準備中)")