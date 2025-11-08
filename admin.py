# admin.py
import streamlit as st
import aiosqlite
import asyncio
import os
from datetime import datetime

DB_PATH = "ads.db"

# Асинхронные функции для Streamlit (обёртка)
def run_async(coro):
    return asyncio.run(coro)

async def get_all_ads():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT id, ad_type, item_type, description, location_key,
                   contact_type, contact_info, status, created_at
            FROM ads
            ORDER BY created_at DESC
        """)
        return await cursor.fetchall()

async def archive_ad_db(ad_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE ads SET status = 'archived' WHERE id = ?", (ad_id,))
        await db.commit()

async def delete_ad_db(ad_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM ads WHERE id = ?", (ad_id,))
        await db.commit()

# === Streamlit UI ===
st.set_page_config(page_title="FilterWhereIsMy — Админка", layout="wide")
st.title("FilterWhereIsMy — Панель модератора")

# 🔐 Простая защита паролем
PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")  # зададим в Render
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    pwd = st.text_input("🔒 Пароль", type="password")
    if st.button("Войти"):
        if pwd == PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Неверный пароль!")
    st.stop()

st.success("✅ Добро пожаловать, модератор!")

# Загрузка данных
ads = run_async(get_all_ads())

if not ads:
    st.info("📭 Нет объявлений.")
else:
    st.write(f"Всего объявлений: {len(ads)}")

    # Фильтры
    col1, col2 = st.columns(2)
    with col1:
        status_filter = st.selectbox("Статус", ["Все", "active", "archived"], index=0)
    with col2:
        type_filter = st.selectbox("Тип", ["Все", "found", "lost"], index=0)

    # Фильтрация
    filtered = []
    for ad in ads:
        ad_id, ad_type, item, desc, loc, c_type, c_info, status, created = ad
        if status_filter != "Все" and status != status_filter:
            continue
        if type_filter != "Все" and ad_type != type_filter:
            continue
        filtered.append(ad)

    # Таблица
    for ad in filtered:
        ad_id, ad_type, item, desc, loc, c_type, c_info, status, created = ad
        dt = datetime.fromisoformat(created).strftime("%d.%m %H:%M")
        emoji = "🔍" if ad_type == "found" else "❓"
        status_badge = "🟢 active" if status == "active" else "⚫ archived"

        with st.expander(f"{emoji} {item} | {loc} | {status_badge} | {dt}", expanded=False):
            st.write(f"**Тип:** {ad_type}")
            st.write(f"**Описание:** {desc or '—'}")
            st.write(f"**Контакт:** {c_info}")
            st.write(f"**ID объявления:** `{ad_id}`")

            col_a, col_b = st.columns(2)
            with col_a:
                if status == "active":
                    if st.button("⏹ Архивировать", key=f"arch_{ad_id}"):
                        run_async(archive_ad_db(ad_id))
                        st.success(f"Объявление {ad_id} архивировано")
                        st.rerun()
            with col_b:
                if st.button("🗑 Удалить", key=f"del_{ad_id}", type="secondary"):
                    run_async(delete_ad_db(ad_id))
                    st.success(f"Объявление {ad_id} удалено")
                    st.rerun()