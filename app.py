import streamlit as st
import pandas as pd
import datetime
import google.generativeai as genai
from sqlalchemy import text
st.set_page_config(page_title="飲食熱量記錄系統", page_icon="🔥", layout="wide")

# -----------------------------------------------------------------------------
# 1. 系統安全：密碼鎖機制
# -----------------------------------------------------------------------------
# def check_password():
#     """驗證使用者密碼是否正確"""
#     def password_entered():
#         # 核對輸入的密碼是否與 secrets 中的密碼相符
#         if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
#             st.session_state["password_correct"] = True
#             del st.session_state["password"]  # 驗證成功後清除輸入框內的密碼紀錄
#         else:
#             st.session_state["password_correct"] = False
#
#     if "password_correct" not in st.session_state:
#         # 第一次進入，顯示密碼輸入框
#         st.title("🔒 系統已鎖定")
#         st.text_input("請輸入專屬密碼以解鎖系統：", type="password", on_change=password_entered, key="password")
#         return False
#     elif not st.session_state["password_correct"]:
#         # 密碼錯誤，顯示錯誤提示
#         st.title("🔒 系統已鎖定")
#         st.text_input("請輸入專屬密碼以解鎖系統：", type="password", on_change=password_entered, key="password")
#         st.error("😕 密碼錯誤，請再試一次。")
#         return False
#     else:
#         # 密碼正確，放行
#         return True
#
# # 如果密碼驗證未通過，就停止執行後續的所有程式碼
# if not check_password():
#     st.stop()

# ==========================================
# 2. 資料庫連線與初始化
# ==========================================
# 建立資料庫連線 (會自動讀取 secrets.toml 中的 connections.postgresql)
conn = st.connection("postgresql", type="sql")


def get_or_create_user():
    with conn.session as s:
        # 使用 mappings() 可以讓我們用字典的方式讀取資料 (例如 user['username'])
        user = s.execute(text("SELECT * FROM users WHERE user_id = 1")).mappings().fetchone()

        if not user:
            # 建立第一筆資料作為預設用戶
            s.execute(text("""
                INSERT INTO users (username, age, gender, height, weight, target_calories)
                VALUES ('主要用戶', 37, '男', 186.0, 95.0, 2200);
            """))
            s.commit()
            user = s.execute(text("SELECT * FROM users WHERE user_id = 1")).mappings().fetchone()
        return user


# 取得目前使用者資料
current_user = get_or_create_user()

# ==========================================
# 3. 資料庫操作函數
# ==========================================
def add_water_record(user_id, amount):
    """將喝水紀錄寫入資料庫"""
    with conn.session as s:
        s.execute(text("""
            INSERT INTO water_records (user_id, amount, record_date, record_time)
            VALUES (:uid, :amt, CURRENT_DATE, CURRENT_TIME)
        """), {"uid": user_id, "amt": amount})
        s.commit()

def get_today_water(user_id):
    """計算今天總共喝了多少水"""
    with conn.session as s:
        result = s.execute(text("""
            SELECT SUM(amount) as total FROM water_records
            WHERE user_id = :uid AND record_date = CURRENT_DATE
        """), {"uid": user_id}).mappings().fetchone()
        return result['total'] if result['total'] else 0

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
    # 改為從資料庫讀取，而不是 session_state
    today_water = get_today_water(current_user['user_id'])

    water_progress = min(today_water / target_water, 1.0)
    st.progress(water_progress)
    st.write(f"**已飲用:** {today_water} / {target_water} ml")

    if st.button("💧 +250ml", use_container_width=True):
        add_water_record(current_user['user_id'], 250)
        st.rerun()  # 重新載入畫面，讓進度條更新

st.divider()

import json


def query_food_nutrition_via_ai(food_name):
    """使用 Gemini API 查詢食物每 100 克的營養資訊"""
    # 從 Secrets 讀取 API Key 並初始化
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("❌ 找不到 GEMINI_API_KEY，請檢查 Streamlit Secrets 設定。")
        return None

    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

    # 建立精準的提示詞
    prompt = f"""
    請提供以下食物的營養資訊（每 100 克）：
    食物名稱：{food_name}

    請嚴格按照以下 JSON 格式返回，不要包含任何額外的 Markdown 標籤或說明文字：
    {{
      "food_name": "食物名稱",
      "calories": 熱量數值（kcal，必須是數字）,
      "protein": 蛋白質數值（g，必須是數字）,
      "carbs": 碳水化合物數值（g，必須是數字）,
      "fat": 脂肪數值（g，必須是數字）,
      "sugar": 糖類數值（g，必須是數字）
    }}
    如果完全無法辨識該食物，請回傳 null。
    """

    try:
        # 使用 2026 年推薦的穩定模型
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)

        # 清理可能包含的 ```json 標籤，確保解析順利
        clean_text = response.text.strip().replace("```json", "").replace("```", "")
        nutrition_data = json.loads(clean_text)
        return nutrition_data
    except Exception as e:
        st.error(f"AI 查詢發生錯誤: {str(e)}")
        return None


# -----------------------------------------------------------------------------
# 4. 飲食記錄主介面與 AI 互動
# -----------------------------------------------------------------------------
st.divider()
st.subheader("➕ 添加飲食記錄")

# 初始化 AI 暫存狀態
if "ai_results" not in st.session_state:
    st.session_state.ai_results = None

with st.expander("展開飲食記錄面板", expanded=True):
    # 基礎輸入欄位
    meal_type = st.selectbox("用餐時間", ["早餐", "午餐", "晚餐", "點心"], key="meal_type_select")
    food_name = st.text_input("✍️ 手動輸入新食物名稱", placeholder="例如：烤雞胸肉、滷肉飯", key="food_name_input")
    food_weight = st.number_input("重量/份量 (克)", min_value=1, value=100, step=10, key="food_weight_input")

    # 按鈕：啟動 AI 查詢
    if st.button("🤖 使用 AI 查詢營養資訊", use_container_width=True):
        if food_name:
            with st.spinner(f"Gemini 正在極速分析 {food_name} 的營養成分..."):
                raw_nutrition = query_food_nutrition_via_ai(food_name)
                if raw_nutrition:
                    st.session_state.ai_results = raw_nutrition
                    st.success("🎉 AI 查詢成功！請在下方確認並調整實際攝取總量。")
                else:
                    st.error("🔍 AI 無法識別該食物，請嘗試換個說法或手動輸入。")
        else:
            st.warning("⚠️ 請先輸入食物名稱再進行 AI 查詢。")

    # 如果有 AI 查詢結果，顯示計算與微調面板
    if st.session_state.ai_results:
        st.markdown("#### 📋 AI 估算結果（每 100g 原料）")
        res = st.session_state.ai_results

        # 顯示每 100g 基準值
        st.text(f"食物判定：{res.get('food_name', food_name)} | 基準：{res.get('calories', 0)} kcal/100g")

        # 自動根據使用者輸入的重量，換算當餐實際攝取總量
        ratio = food_weight / 100.0

        st.markdown(f"#### 🍽️ 本餐攝取總量預估 ({food_weight}克)")
        st.caption("您可以直接修改下方數值，修正 AI 估計的誤差：")

        # 讓使用者可以微調數值
        calc_cal = st.number_input("總熱量 (kcal)", value=float(res.get('calories', 0) * ratio), step=5.0)

        c_item1, c_item2, c_item3, c_item4 = st.columns(4)
        with c_item1:
            calc_carbs = st.number_input("碳水化合物 (g)", value=float(res.get('carbs', 0) * ratio), step=1.0)
        with c_item2:
            calc_protein = st.number_input("蛋白質 (g)", value=float(res.get('protein', 0) * ratio), step=1.0)
        with c_item3:
            calc_fat = st.number_input("脂肪 (g)", value=float(res.get('fat', 0) * ratio), step=1.0)
        with c_item4:
            calc_sugar = st.number_input("添加糖 (g)", value=float(res.get('sugar', 0) * ratio), step=1.0)

        if st.button("✅ 確認並將此餐記錄至資料庫", type="primary", use_container_width=True):
            # 這裡我們需要呼叫寫入資料庫的函數 (將在下一步完全補齊)
            with conn.session as s:
                s.execute(text("""
                    INSERT INTO diet_records (
                        user_id, food_name, meal_type, weight, calories, 
                        carbs, protein, fat, sugar, record_date, ai_queried
                    ) VALUES (
                        :uid, :name, :m_type, :weight, :cal, 
                        :carbs, :protein, :fat, :sugar, CURRENT_DATE, true
                    )
                """), {
                    "uid": current_user['user_id'], "name": food_name, "m_type": meal_type,
                    "weight": food_weight, "cal": calc_cal, "carbs": calc_carbs,
                    "protein": calc_protein, "fat": calc_fat, "sugar": calc_sugar
                })
                s.commit()

            st.toast(f"已成功加入【{meal_type}】: {food_name}！", icon="🥗")
            # 清除暫存狀態並刷新頁面
            st.session_state.ai_results = None
            st.rerun()