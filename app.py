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
def get_today_diet_summary(user_id):
    """從資料庫加總今日已攝取的熱量與各營養素總和"""
    with conn.session as s:
        result = s.execute(text("""
            SELECT 
                COALESCE(SUM(calories), 0) as total_cal,
                COALESCE(SUM(carbs), 0) as total_carbs,
                COALESCE(SUM(protein), 0) as total_protein,
                COALESCE(SUM(fat), 0) as total_fat,
                COALESCE(SUM(sugar), 0) as total_sugar
            FROM diet_records
            WHERE user_id = :uid AND record_date = CURRENT_DATE
        """), {"uid": user_id}).mappings().fetchone()
        return result

def get_today_diet_list(user_id):
    """取得今天所有的用餐明細列表"""
    with conn.session as s:
        results = s.execute(text("""
            SELECT record_id, food_name, meal_type, weight, calories, carbs, protein, fat, sugar
            FROM diet_records
            WHERE user_id = :uid AND record_date = CURRENT_DATE
            ORDER BY 
                CASE meal_type 
                    WHEN '早餐' THEN 1 
                    WHEN '午餐' THEN 2 
                    WHEN '晚餐' THEN 3 
                    WHEN '點心' THEN 4 
                    ELSE 5 
                END, record_id DESC
        """), {"uid": user_id}).mappings().fetchall()
        return results

def delete_diet_record(record_id):
    """刪除指定的飲食紀錄"""
    with conn.session as s:
        s.execute(text("DELETE FROM diet_records WHERE record_id = :rid"), {"rid": record_id})
        s.commit()


def get_historical_food_list(user_id):
    """
    撈取使用者過去吃過的所有食物列表，按使用頻率與最後使用時間排序。
    回傳一個清單，方便放入下拉選單。
    """
    with conn.session as s:
        results = s.execute(text("""
            SELECT food_name, COUNT(*) as usage_count, MAX(record_date) as last_used
            FROM diet_records
            WHERE user_id = :uid
            GROUP BY food_name
            ORDER BY usage_count DESC, last_used DESC
            LIMIT 50
        """), {"uid": user_id}).mappings().fetchall()

        # 只取出食物名稱組成一個 List
        return [r['food_name'] for r in results]


def get_food_nutrition_by_name(user_id, food_name):
    """
    當使用者選了某個歷史食物，直接去抓最近一次吃這個食物時的『每克營養素比例』，
    以便依據新重量等比例放大縮小。
    """
    with conn.session as s:
        # 找最近一筆該食物的紀錄
        result = s.execute(text("""
            SELECT calories, carbs, protein, fat, sugar, weight
            FROM diet_records
            WHERE user_id = :uid AND food_name = :name
            ORDER BY record_date DESC, record_id DESC
            LIMIT 1
        """), {"uid": user_id, "name": food_name}).mappings().fetchone()

        if result and result['weight'] > 0:
            w = result['weight']
            # 換算回每 100g 的營養素，方便後續計算
            return {
                "calories": (result['calories'] / w) * 100,
                "carbs": (result['carbs'] / w) * 100,
                "protein": (result['protein'] / w) * 100,
                "fat": (result['fat'] / w) * 100,
                "sugar": (result['sugar'] / w) * 100
            }
        return None
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
# -----------------------------------------------------------------------------
# 側邊栏：固定基準目標
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("👤 用戶資訊")
    st.write(f"📅 **今天是第 {day_count} 天**")

    st.divider()
    st.subheader("🎯 每日固定目標")

    # 依需求直接固定數值
    target_calories = 1883
    target_protein = 125.0
    target_fat = 63.0
    target_carbs = 210.0
    target_sugar = 25.0
    target_water = 2000

    st.write(f"🔥 **目標熱量:** {target_calories} kcal")
    st.write(f"🍚 **碳水化合物:** {target_carbs} g")
    st.write(f"🥩 **蛋白質:** {target_protein} g")
    st.write(f"🥑 **脂肪:** {target_fat} g")
    st.write(f"🍬 **添加糖上限:** <{target_sugar} g")
    st.write(f"💧 **水分目標:** {target_water} ml")
# -----------------------------------------------------------------------------
# 主畫面：今日數據動態統計
# -----------------------------------------------------------------------------
# 呼叫函數取得今日最新加總數據
diet_summary = get_today_diet_summary(current_user['user_id'])

# 三大板塊佈局
col1, col2, col3 = st.columns(3)
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown("### 🔥 熱量攝取")
    current_cal = int(diet_summary['total_cal'])
    cal_progress = min(current_cal / target_calories, 1.0) if target_calories > 0 else 0.0
    st.progress(cal_progress)
    st.write(f"**已攝取:** {current_cal:,} / {target_calories:,} kcal")

    remaining_cal = target_calories - current_cal
    if remaining_cal >= 0:
        st.write(f"**剩餘:** {remaining_cal:,} kcal")
    else:
        st.markdown(f"💥 **爆卡: 超標 {abs(remaining_cal):,} kcal!**")

with col2:
    st.markdown("### 📊 📊 三大營養素")
    # 碳水
    c_carbs = diet_summary['total_carbs']
    carbs_p = min(c_carbs / target_carbs, 1.0) if target_carbs > 0 else 0.0
    st.write(f"🍚 碳水: {c_carbs:.1f}g / {target_carbs:.0f}g ({carbs_p * 100:.0f}%)")
    st.progress(carbs_p)

    # 蛋白
    c_protein = diet_summary['total_protein']
    protein_p = min(c_protein / target_protein, 1.0) if target_protein > 0 else 0.0
    st.write(f"🥩 蛋白: {c_protein:.1f}g / {target_protein:.0f}g ({protein_p * 100:.0f}%)")
    st.progress(protein_p)

    # 脂肪
    c_fat = diet_summary['total_fat']
    fat_p = min(c_fat / target_fat, 1.0) if target_fat > 0 else 0.0
    st.write(f"🥑 脂肪: {c_fat:.1f}g / {target_fat:.0f}g ({fat_p * 100:.0f}%)")
    st.progress(fat_p)

with col3:
    st.markdown("### 🍬 糖分攝取")
    c_sugar = diet_summary['total_sugar']
    sugar_p = min(c_sugar / target_sugar, 1.0) if target_sugar > 0 else 0.0

    # 根據是否超標給予進度條與文字警告
    if c_sugar > target_sugar:
        st.markdown(f"⚠️ **糖分超標警告！**")
        st.write(f"🍬 已攝取: **{c_sugar:.1f}g** / {target_sugar:.0f}g")
        st.progress(sugar_p)  # 超標時進度條滿格
    else:
        st.write(f"🍬 已攝取: {c_sugar:.1f}g / {target_sugar:.0f}g ({sugar_p * 100:.0f}%)")
        st.progress(sugar_p)

with col4:
    st.markdown("### 💧 今日水分")
    today_water = get_today_water(current_user['user_id'])
    water_progress = min(today_water / target_water, 1.0)
    st.progress(water_progress)
    st.write(f"**已飲用:** {today_water:,} / {target_water:,} ml")

    if st.button("💧 +250ml", use_container_width=True):
        add_water_record(current_user['user_id'], 250)
        st.rerun()

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
        model = genai.GenerativeModel("gemini-2.5-flash")
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
    # 1. 基礎欄位選擇
    meal_type = st.selectbox("用餐時間", ["早餐", "午餐", "晚餐", "點心"], key="meal_type_select")

    # 新增：計量單位切換 (公克 vs 份數)
    unit_type = st.radio("計量單位", ["公克 (g)", "個/顆/份"], horizontal=True)

    if unit_type == "公克 (g)":
        food_weight = st.number_input("輸入重量 (公克)", min_value=1, value=100, step=10)
    else:
        food_units = st.number_input("輸入數量 (個/顆/份)", min_value=0.1, value=1.0, step=0.5)
        # 為了相容原本資料庫的 weight 欄位，我們將「1份」在後台定義為「100克基準」
        food_weight = int(food_units * 100)

    # 2. 分頁切換
    tab1, tab2 = st.tabs(["📋 從歷史記錄選擇", "✍️ 使用 AI 查詢新食物"])

    final_food_name = ""
    base_nutrition = None

    with tab1:
        hist_foods = get_historical_food_list(current_user['user_id'])
        if not hist_foods:
            st.info("💡 您目前還沒有歷史飲食紀錄喔！請先至隔壁分頁使用 AI 新增第一筆食物。")
        else:
            selected_hist = st.selectbox("請選擇之前吃過的食物：", options=["-- 請選擇 --"] + hist_foods)
            if selected_hist != "-- 請選擇 --":
                final_food_name = selected_hist
                base_nutrition = get_food_nutrition_by_name(current_user['user_id'], selected_hist)

    with tab2:
        # 微調提示詞引導，讓使用者可以更自由輸入
        food_name = st.text_input("✍️ 輸入新食物名稱", placeholder="例如：雞蛋、大麥克漢堡、烤雞胸肉",
                                  key="food_name_input")

        if st.button("🤖 使用 AI 查詢營養資訊", use_container_width=True):
            if food_name:
                with st.spinner(f"Gemini 正在分析 {food_name}..."):
                    raw_nutrition = query_food_nutrition_via_ai(food_name)
                    if raw_nutrition:
                        st.session_state.ai_results = raw_nutrition
                        st.success("🎉 AI 查詢成功！")
                    else:
                        st.error("🔍 AI 無法識別，請嘗試換個說法。")
            else:
                st.warning("⚠️ 請先輸入食物名稱。")

        if st.session_state.ai_results and food_name:
            final_food_name = food_name
            base_nutrition = st.session_state.ai_results

    # 3. 統一換算與渲染
    if final_food_name and base_nutrition:
        st.markdown("---")

        # 顯示友善的名稱
        if unit_type == "公克 (g)":
            st.markdown(f"#### 🍽️ 本餐攝取總量預估 ({final_food_name} - {food_weight} g)")
        else:
            st.markdown(f"#### 🍽️ 本餐攝取總量預估 ({final_food_name} - {food_units} 個/顆/份)")

        # 核心換算邏輯
        ratio = food_weight / 100.0

        calc_cal = st.number_input("總熱量 (kcal)", value=float(base_nutrition.get('calories', 0) * ratio), step=5.0)

        c_item1, c_item2, c_item3, c_item4 = st.columns(4)
        with c_item1:
            calc_carbs = st.number_input("碳水化合物 (g)", value=float(base_nutrition.get('carbs', 0) * ratio),
                                         step=1.0)
        with c_item2:
            calc_protein = st.number_input("蛋白質 (g)", value=float(base_nutrition.get('protein', 0) * ratio),
                                           step=1.0)
        with c_item3:
            calc_fat = st.number_input("脂肪 (g)", value=float(base_nutrition.get('fat', 0) * ratio), step=1.0)
        with c_item4:
            calc_sugar = st.number_input("添加糖 (g)", value=float(base_nutrition.get('sugar', 0) * ratio), step=1.0)

        if st.button("✅ 確認並將此餐記錄至資料庫", type="primary", use_container_width=True):
            with conn.session as s:
                s.execute(text("""
                    INSERT INTO diet_records (
                        user_id, food_name, meal_type, weight, calories, 
                        carbs, protein, fat, sugar, record_date, ai_queried, is_from_history
                    ) VALUES (
                        :uid, :name, :m_type, :weight, :cal, 
                        :carbs, :protein, :fat, :sugar, CURRENT_DATE, :ai_q, :is_hist
                    )
                """), {
                    "uid": current_user['user_id'], "name": final_food_name, "m_type": meal_type,
                    "weight": food_weight, "cal": calc_cal, "carbs": calc_carbs,
                    "protein": calc_protein, "fat": calc_fat, "sugar": calc_sugar,
                    "ai_q": True if st.session_state.ai_results else False,
                    "is_hist": True if tab1 else False
                })
                s.commit()

            st.toast(f"已成功加入【{meal_type}】: {final_food_name}！", icon="🥗")
            st.session_state.ai_results = None
            st.rerun()

# -----------------------------------------------------------------------------
# 5. 用餐記錄列表展示
# -----------------------------------------------------------------------------
st.divider()
st.subheader("🍽️ 今日用餐記錄明細")

today_records = get_today_diet_list(current_user['user_id'])

if not today_records:
    st.info("💡 今天還沒有任何飲食紀錄喔！趕快使用上方的 AI 面板吃點東西吧！")
else:
    # 依餐別用精緻的卡片或文字排版輸出
    for r in today_records:
        # 用 st.container 畫出整齊的邊框區塊
        with st.container():
            # 切分左右兩欄：左邊顯示食物數據，右邊放一個精簡的刪除按鈕
            item_col, btn_col = st.columns([5, 1])

            with item_col:
                # 依餐別給予不同圖示
                emoji_map = {"早餐": "🍳", "午餐": "🍜", "晚餐": "🍱", "點心": "🍰"}
                emoji = emoji_map.get(r['meal_type'], "🍽️")

                st.markdown(
                    f"#### {emoji} {r['meal_type']} | **{r['food_name']}** ({r['weight']:.0f}g) — `{r['calories']:.0f} kcal`")
                st.caption(
                    f"🧪 營養素分配 — 碳水: {r['carbs']:.1f}g | 蛋白: {r['protein']:.1f}g | 脂肪: {r['fat']:.1f}g | 糖: {r['sugar']:.1f}g")

            with btn_col:
                # 垂直留白對齊按鈕
                st.write("")
                # 每筆紀錄綁定獨立的 key 避免衝突
                if st.button("🗑️ 刪除", key=f"del_{r['record_id']}", use_container_width=True):
                    delete_diet_record(r['record_id'])
                    st.toast(f"已刪除 {r['food_name']} 的紀錄", icon="🗑️")
                    st.rerun()
        st.write("")  # 稍微留白