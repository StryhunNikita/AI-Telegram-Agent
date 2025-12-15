import os
import html
import asyncio

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
from typing import Optional, Tuple

from .llm import ask_assistant, create_vector_store
from .db import db
from .agent_files import agent_file_manager

from .log_utils import send_ai_log, send_admin_user_message
from .config import ADMIN_IDS
from .takeover import takeover_router
from datetime import datetime, timezone
TAKEOVER_TIMEOUT_MINUTES = 20

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

bot = Bot(
    token=TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

dp.include_router(takeover_router)

DEFAULT_AGENT_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    """Ты дружелюбный и умный Telegram-ассистент.
    Отвечай кратко, по делу, простым понятным языком.
    Если пользователь пишет на русском — отвечай на русском.
    Если вопрос непонятен — попроси уточнить.
    """
)

AGENT_PROMPT = DEFAULT_AGENT_PROMPT
WAITING_FOR_PROMPT: set[int] = set()
AGENT_VECTOR_STORE_ID: Optional[str] = None

admin_menu_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Изменить промпт", callback_data="admin_edit_prompt")],
        [InlineKeyboardButton(text="Файлы агента", callback_data="admin_files")],
    ]
)

admin_files_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Загрузить файл", callback_data="admin_files_upload")],
        [InlineKeyboardButton(text="Список файлов", callback_data="admin_files_list")],
    ]
)


@dp.message(Command("admin"))
async def admin_menu(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("У вас нет доступа к админке!")

    await message.answer(
        "Админ-меню агента:\n\n"
        "1️⃣ Изменить промпт агента\n"
        "2️⃣ Управлять файлами (загрузка/удаление/скачивание)",
        reply_markup=admin_menu_kb,
    )


@dp.callback_query(F.data == "admin_edit_prompt")
async def on_admin_edit_prompt(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("Нет доступа", show_alert=True)

    WAITING_FOR_PROMPT.add(callback.from_user.id)

    safe_prompt = html.escape(AGENT_PROMPT)

    await callback.message.answer(
        "Отправь новый промпт для агента одним сообщением.\n\n"
        f"Текущий промпт сейчас:\n<code>{safe_prompt}</code>\n\n"
    )
    await callback.answer()


async def load_agent_vector_store_from_db():
    global AGENT_VECTOR_STORE_ID

    value = await db.get_setting("agent_vector_store_id")
    if value is None:
        vector_store_id = await create_vector_store("Agent knowledge base")
        await db.set_setting("agent_vector_store_id", vector_store_id)
        AGENT_VECTOR_STORE_ID = vector_store_id
        print(f"Vector store not found in DB, created new: {vector_store_id}")
    else:
        AGENT_VECTOR_STORE_ID = value
        print(f"Vector store loaded from DB: {value}")


async def load_agent_prompt_from_db():
    global AGENT_PROMPT

    value = await db.get_setting("agent_prompt")
    if value is None:
        AGENT_PROMPT = DEFAULT_AGENT_PROMPT
        await db.set_setting("agent_prompt", DEFAULT_AGENT_PROMPT)
        print("Agent prompt not found in DB, set default.")
    else:
        AGENT_PROMPT = value
        print("Agent prompt loaded from DB.")


@dp.callback_query(F.data == "admin_files")
async def on_admin_files(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("Нет доступа", show_alert=True)

    await callback.message.answer(
        "Работа с файлами агента.\n\n"
        "Выбери действие:",
        reply_markup=admin_files_kb,
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_files_upload")
async def on_admin_files_upload(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("Нет доступа", show_alert=True)

    agent_file_manager.set_waiting_for_file(callback.from_user.id)

    await callback.message.answer("Отправь файл (документ) одним сообщением.")
    await callback.answer()


@dp.callback_query(F.data == "admin_files_list")
async def on_admin_files_list(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("Нет доступа", show_alert=True)

    files = await agent_file_manager.get_recent_files(limit=10, offset=0)
    
    if not files:
        await callback.message.answer("Файлов агента пока нет.")
        await callback.answer()
        return

    lines = ["Сохранённые файлы агента:\n"]
    keyboard_rows = []

    for row in files:
        file_id = row["id"]
        filename = row["filename"]
        created = row["created_at"].strftime("%Y-%m-%d %H:%M")

        lines.append(f"{file_id}. <b>{html.escape(filename)}</b> ({created})")

        keyboard_rows.append(
            [
                InlineKeyboardButton(
                    text=f"Скачать",
                    callback_data=f"admin_file_download:{file_id}",
                ),
                InlineKeyboardButton(
                    text="Удалить",
                    callback_data=f"admin_file_delete:{file_id}",
                ),
            ]
        )

    text = "\n".join(lines)
    files_kb = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

    await callback.message.answer(text, reply_markup=files_kb)
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_file_download:"))
async def on_admin_file_download(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("Нет доступа", show_alert=True)

    try:
        file_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return await callback.answer("Некорректный ID файла.", show_alert=True)

    file_row = await agent_file_manager.get_file_info(file_id)
    if not file_row:
        return await callback.answer("Файл не найден в базе.", show_alert=True)

    telegram_file_id = file_row["telegram_file_id"]
    filename = file_row["filename"]

    await callback.message.answer_document(
        document=telegram_file_id,
        caption=f"Файл: {filename}",
    )

    await callback.answer("Файл отправлен.")


@dp.callback_query(F.data.startswith("admin_file_delete:"))
async def on_admin_file_delete(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("Нет доступа", show_alert=True)

    try:
        file_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return await callback.answer("Некорректный ID файла.", show_alert=True)

    success = await agent_file_manager.delete_file(file_id)
    if not success:
        return await callback.answer("Файл не найден или уже удалён.", show_alert=True)

    await callback.message.answer(f"Файл с ID {file_id} удалён из базы.")
    await callback.answer("Удалено.")


async def should_route_to_admin(user_telegram_id: int) -> Tuple[bool, Optional[int]]:
    """
    Возвращает:
      (True, admin_id)  -> надо переслать админу (ручной режим активен)
      (False, None)     -> надо обслуживать ИИ (режим ai или ручной протух)
    """
    mode, admin_id, taken_at = await db.get_conversation_state(user_telegram_id)

    if mode is None:
        return False, None

    if mode != "admin":
        return False, None

    if not admin_id or taken_at is None:
        await db.set_conversation_mode(user_telegram_id=user_telegram_id, mode="ai", taken_by_admin_id=None)
        return False, None

    now = datetime.now(timezone.utc)
    if taken_at.tzinfo is None:
        taken_at = taken_at.replace(tzinfo=timezone.utc)

    minutes_passed = (now - taken_at).total_seconds() / 60

    if minutes_passed > TAKEOVER_TIMEOUT_MINUTES:
        await db.set_conversation_mode(user_telegram_id=user_telegram_id, mode="ai", taken_by_admin_id=None)
        return False, None

    return True, int(admin_id)


@dp.message(F.chat.type == "private", ~F.text.startswith("/"))
async def handle_message(message: Message):
    global AGENT_PROMPT

    user_id = message.from_user.id
    text = message.text or ""

    if user_id in ADMIN_IDS and user_id in WAITING_FOR_PROMPT:
        new_prompt = text.strip()

        if not new_prompt:
            return await message.answer("Промпт не может быть пустым. Отправь текст ещё раз.")

        AGENT_PROMPT = new_prompt
        WAITING_FOR_PROMPT.remove(user_id)
        await db.set_setting("agent_prompt", AGENT_PROMPT)

        safe_prompt = html.escape(AGENT_PROMPT)
        await message.answer(
            "Промпт агента обновлён!\n\n"
            f"Текущий промпт:\n<code>{safe_prompt}</code>"
        )
        return

    if user_id in ADMIN_IDS and agent_file_manager.is_waiting_for_file(user_id):
        response = await agent_file_manager.handle_file_upload(message, AGENT_VECTOR_STORE_ID)
        if response:
            await message.answer(response)
        return

    if user_id in ADMIN_IDS:
        target_user_id = await db.get_admin_active_chat(user_id)

        if not target_user_id:
            await message.answer("Нет активного диалога. Открой чат через кнопку в лог-группе.")
            return

        await bot.send_message(chat_id=target_user_id, text=text)
        await message.answer("Отправлено клиенту.")

        internal_user_id = await db.save_user(telegram_id=target_user_id, username=None)
        await db.save_message(user_id=internal_user_id, role="admin", content=text)

        return

    route_to_admin, admin_id = await should_route_to_admin(message.from_user.id)

    if route_to_admin:
        username = message.from_user.username
        user_label = f"@{username}" if username else f"id:{user_id}"

        await bot.send_message(
            chat_id=admin_id,
            text=f"Сообщение от клиента ({user_label}):\n{text}"
        )

        await send_admin_user_message(
            bot=bot,
            user=message.from_user,
            user_message=text,
        )

        internal_user_id = await db.save_user(
            telegram_id=message.from_user.id,
            username=message.from_user.username
        )
        await db.save_message(user_id=internal_user_id, role="user", content=text)
        return

    internal_user_id = await db.save_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username
    )

    user_text = message.text or ""
    await db.save_message(user_id=internal_user_id, role="user", content=user_text)

    waiting_message = await message.answer("думаю...")

    try:
        reply_text = await ask_assistant(
            user_text,
            AGENT_PROMPT,
            vector_store_id=AGENT_VECTOR_STORE_ID,
        )
    except Exception as e:
        await waiting_message.edit_text(f"Произошла ошибка: {e}")
        return

    await db.save_message(user_id=internal_user_id, role="assistant", content=reply_text)
    await waiting_message.edit_text(reply_text, parse_mode=None)

    await send_ai_log(
        bot=message.bot,            
        user=message.from_user,   
        user_message=user_text,  
        ai_answer=reply_text,       
    )


async def main():
    await db.connect()
    await db.create_table()
    await load_agent_prompt_from_db()
    await load_agent_vector_store_from_db()

    try:
        print("Bot started...")
        await dp.start_polling(bot)
    finally:
        await db.disconnect()
        print("Bot stopped.")

if __name__ == "__main__":
    asyncio.run(main())