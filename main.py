import os
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.filters import CommandStart
from dotenv import load_dotenv

from database import (
    init_db, ensure_user, create_ad, get_active_ads_by_type_and_location,
    get_user_ads, archive_ad, blob_to_embedding, get_ad_by_id
)
from search import encode_text, rank_ads_by_query

# === НАСТРОЙКИ ===
load_dotenv()
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не задан в .env!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

# === КОНСТАНТЫ ===
ITEM_TYPES = [
    "Карту-пропуск", "Гардеробный номерок", "Ключи",
    "Повербанк", "Зонтик", "Кошелёк", "Другое…"
]
LOCATIONS = {
    "ФЭБ (ВДНХ)": "м. ВДНХ, ул. Кибальчича, д. 1, стр. 2",
    "Финансовый (Китай-город)": "м. Китай-город, Малый Златоустинский пер., д. 7, стр. 1",
    "Финансовый (Филёвский парк)": "м. Филёвский парк, ул. Олеко Дундича, д. 23",
    "ФНАБА (Динамо)": "м. Динамо, ул. Верхняя Масловка, д. 15",
    "ФМЭО (Аэропорт)": "м. Аэропорт, Ленинградский просп., д. 49",
    "ВШУ (Динамо)": "м. Динамо, ул. Верхняя Масловка, д. 15",
    "Юрфак (Семёновская)": "м. Семёновская, ул. Щербаковская, д. 38",
    "ФСНиМК (Аэропорт)": "м. Аэропорт, Ленинградский просп., д. 49",
    "ИТиАБД (Рязанский просп.)": "м. Рязанский проспект, 4-й Вешняковский пр., д. 4",
    "ИОО (Филёвский парк)": "м. Филёвский парк, ул. Олеко Дундича, д. 23"
}
LOCATION_CHOICES = list(LOCATIONS.keys()) + ["Не помню"]

# === FSM ===
class FoundFlow(StatesGroup):
    type = State()
    description = State()
    location = State()
    place_detail = State()
    contact_type = State()
    contact_or_drop = State()

class LostFlow(StatesGroup):
    type = State()
    location = State()
    # далее — просмотр или создание

# === КЛАВИАТУРЫ ===
def main_menu_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Нашёл"), KeyboardButton(text="❓ Потерял")],
            [KeyboardButton(text="📋 Мои объявления")]
        ],
        resize_keyboard=True
    )

def item_type_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=item)] for item in ITEM_TYPES],
        resize_keyboard=True, one_time_keyboard=True
    )

def location_kb(include_forget=True):
    buttons = [KeyboardButton(text=loc) for loc in LOCATIONS.keys()]
    if include_forget:
        buttons.append(KeyboardButton(text="Не помню"))
    kb = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)

def skip_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Пропустить")]],
        resize_keyboard=True
    )

def contact_type_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Оставил в…", callback_data="contact_type:drop")],
        [InlineKeyboardButton(text="Свяжитесь со мной", callback_data="contact_type:contact")]
    ])

def archive_kb(ad_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏹️ Завершить", callback_data=f"archive:{ad_id}")]
    ])

# === ВСПОМОГАТЕЛЬНЫЕ ===
def format_ad_message(ad_row, is_owner=False) -> str:
    ad_id, user_id, ad_type, item_type, desc, photo, loc, place, c_type, c_info, _, status, created = ad_row
    emoji = "🔍" if ad_type == "found" else "❓"
    status_label = "✅ АКТИВНОЕ" if status == "active" else "⏹ АРХИВ"
    place_line = f" — {place}" if place else ""
    contact_line = ""
    if c_type == "drop":
        contact_line = f"📥 Оставил в: {c_info}"
    else:
        contact_line = f"📞 Связаться: {c_info}"

    dt = datetime.fromisoformat(created).strftime("%d.%m.%Y")
    msg = f"[{status_label}] {emoji} {ad_type == 'found' and 'Нашёл' or 'Потерял'}: {item_type}\n"
    msg += f"📍 {loc}{place_line}\n"
    if desc:
        msg += f"📝 {desc}\n"
    msg += f"{contact_line}"
    if status == "archived":
        msg += f"\n⏹ Завершено {dt}"
    return msg

# === ОБРАБОТЧИКИ ===
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await ensure_user(message.from_user.id)
    await message.answer(
        "🎓 *WhereIsMy* — бот для поиска потерянных вещей в корпусах университета.\n\n"
        "Выберите действие:",
        reply_markup=main_menu_kb(),
        parse_mode="Markdown"
    )

# --- НАШЁЛ ---
@router.message(F.text == "🔍 Нашёл")
async def found_start(message: Message, state: FSMContext):
    await state.set_state(FoundFlow.type)
    await message.answer("Что вы нашли?", reply_markup=item_type_kb())

@router.message(FoundFlow.type, F.text.in_(ITEM_TYPES))
async def found_type(message: Message, state: FSMContext):
    await state.update_data(item_type=message.text)
    await state.set_state(FoundFlow.description)
    await message.answer("Опишите предмет (до 100 символов). Можно прикрепить фото.", reply_markup=skip_kb())

@router.message(FoundFlow.description)
async def found_desc(message: Message, state: FSMContext):
    text = message.text or message.caption or ""
    if text == "Пропустить":
        text = ""
    elif len(text) > 100:
        await message.answer("Не более 100 символов. Повторите.")
        return
    photo_id = message.photo[-1].file_id if message.photo else None
    await state.update_data(description=text, photo_file_id=photo_id)
    await state.set_state(FoundFlow.location)
    await message.answer("Где нашли?", reply_markup=location_kb(include_forget=False))

@router.message(FoundFlow.location, F.text.in_(LOCATIONS))
async def found_location(message: Message, state: FSMContext):
    await state.update_data(location=message.text)
    await state.set_state(FoundFlow.place_detail)
    await message.answer("Уточните место (необязательно):", reply_markup=skip_kb())

@router.message(FoundFlow.place_detail)
async def found_place(message: Message, state: FSMContext):
    detail = "" if message.text == "Пропустить" else message.text
    await state.update_data(place_detail=detail)
    await state.set_state(FoundFlow.contact_type)
    await message.answer("Как передать находку?", reply_markup=contact_type_kb())

@router.callback_query(F.data.startswith("contact_type:"))
async def found_contact_type(callback: CallbackQuery, state: FSMContext):
    ct = callback.data.split(":")[1]
    await state.update_data(contact_type=ct)
    await state.set_state(FoundFlow.contact_or_drop)
    if ct == "drop":
        await callback.message.answer("Где оставили находку?")
    else:
        await callback.message.answer("Как с вами связаться?")
    await callback.answer()

@router.message(FoundFlow.contact_or_drop)
async def found_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    contact_info = message.text

    # === ВЕКТОРИЗАЦИЯ ===
    text_for_embedding = f"{data['item_type']} {data['description']}"
    embedding = encode_text(text_for_embedding)

    ad_id = await create_ad(
        user_id=user_id,
        ad_type="found",
        item_type=data["item_type"],
        description=data["description"],
        photo_file_id=data["photo_file_id"],
        location_key=data["location"],
        place_detail=data["place_detail"],
        contact_type=data["contact_type"],
        contact_info=contact_info,
        embedding=embedding
    )

    await message.answer("✅ Объявление о находке опубликовано!", reply_markup=main_menu_kb())
    await state.clear()

# --- ПОТЕРЯЛ ---
@router.message(F.text == "❓ Потерял")
async def lost_start(message: Message, state: FSMContext):
    await state.set_state(LostFlow.type)
    await message.answer("Что потеряли?", reply_markup=item_type_kb())

@router.message(LostFlow.type, F.text.in_(ITEM_TYPES))
async def lost_type(message: Message, state: FSMContext):
    await state.update_data(item_type=message.text)
    await state.set_state(LostFlow.location)
    await message.answer("Где потеряли?", reply_markup=location_kb(include_forget=True))

@router.message(LostFlow.location, F.text.in_(LOCATION_CHOICES))
async def lost_location(message: Message, state: FSMContext):
    location = message.text if message.text != "Не помню" else None
    await state.update_data(location=location)

    # === ПОИСК ===
    data = await state.get_data()
    item_type = data["item_type"]

    ads = await get_active_ads_by_type_and_location(item_type, location)
    if not ads:
        await message.answer(
            "🔍 Ничего не найдено.\nХотите подать объявление?",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="➕ Подать объявление")],
                    [KeyboardButton(text="↩️ Назад")]
                ],
                resize_keyboard=True
            )
        )
        return

    # === ВЕКТОРНЫЙ РЕЙТИНГ ===
    query_text = item_type  # можно улучшить: добавить "потерял [item]"
    query_emb = encode_text(query_text)
    ads_with_emb = [(ad, blob_to_embedding(ad[10])) for ad in ads]
    ranked = rank_ads_by_query(query_emb, ads_with_emb)

    # Показываем ТОП-5
    for i, (ad, sim) in enumerate(ranked[:5], 1):
        msg = format_ad_message(ad)
        await message.answer(msg)

    await message.answer("Нашли свою вещь? Свяжитесь с автором объявления.")

# --- МОИ ОБЪЯВЛЕНИЯ ---
@router.message(F.text == "📋 Мои объявления")
async def my_ads(message: Message):
    user_id = message.from_user.id
    ads = await get_user_ads(user_id, status="active")
    if not ads:
        await message.answer("📭 У вас нет активных объявлений.", reply_markup=main_menu_kb())
        return

    for ad in ads:
        # Подготавливаем данные для format_ad_message (дополняем)
        full_ad = (ad[0], user_id, *ad[1:9], None, ad[8], ad[9])  # подделываем под формат
        msg = format_ad_message(full_ad, is_owner=True)
        await message.answer(msg, reply_markup=archive_kb(ad[0]))

# --- АРХИВАЦИЯ ---
@router.callback_query(F.data.startswith("archive:"))
async def handle_archive(callback: CallbackQuery):
    try:
        ad_id = int(callback.data.split(":")[1])
        user_id = callback.from_user.id
        success = await archive_ad(ad_id, user_id)
        if success:
            await callback.message.edit_text(
                callback.message.text.replace("[✅ АКТИВНОЕ]", "[⏹ АРХИВ]")
                + f"\n⏹ Завершено {datetime.now().strftime('%d.%m.%Y')}"
            )
            await callback.answer("✅ Объявление завершено.")
        else:
            await callback.answer("❌ Не удалось завершить (не ваше объявление).", show_alert=True)
    except Exception as e:
        logging.error(f"Ошибка архивации: {e}")
        await callback.answer("⚠️ Ошибка. Попробуйте позже.", show_alert=True)

# === ЗАПУСК ===
dp.include_router(router)

import os
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import (
    SimpleRequestHandler,
    setup_application,
)
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

# Получаем токен и настройки
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL", "https://your-bot.onrender.com")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

# Создаём приложение
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dp.include_router(router)

app = web.Application()
SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
setup_application(app, dp, bot=bot)

# Health-check эндпоинт (обязательно для Render!)
async def ping(request):
    return web.Response(text="OK")

app.router.add_get("/ping", ping)

if __name__ == "__main__":
    # Локально можно использовать polling (для тестов)
    if os.getenv("RENDER") is None:
        import asyncio
        asyncio.run(dp.start_polling(bot))
    else:
        # На Render — запускаем веб-сервер
        port = int(os.getenv("PORT", 10000))
        web.run_app(app, host="0.0.0.0", port=port)