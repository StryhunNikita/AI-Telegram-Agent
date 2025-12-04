import os
import html
import asyncio

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
from typing import Optional

from .llm import ask_assistant
from .db import db
from .agent_files import agent_file_manager

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = Bot(
    token=TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

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
    if message.from_user.id != ADMIN_ID:
        return await message.answer("У вас нет доступа к админке!")

    await message.answer(
        "Админ-меню агента:\n\n"
        "1️⃣ Изменить промпт агента\n"
        "2️⃣ Управлять файлами (загрузка/удаление/скачивание)",
        reply_markup=admin_menu_kb,
    )


@dp.callback_query(F.data == "admin_edit_prompt")
async def on_admin_edit_prompt(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа", show_alert=True)

    WAITING_FOR_PROMPT.add(callback.from_user.id)

    safe_prompt = html.escape(AGENT_PROMPT)

    await callback.message.answer(
        "Отправь новый промпт для агента одним сообщением.\n\n"
        f"Текущий промпт сейчас:\n<code>{safe_prompt}</code>\n\n"
    )
    await callback.answer()

from .llm import create_vector_store

async def load_agent_vector_store_from_db():
    """
    Загружаем id vector store из БД или создаём новый.
    """
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
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа", show_alert=True)

    await callback.message.answer(
        "Работа с файлами агента.\n\n"
        "Выбери действие:",
        reply_markup=admin_files_kb,
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_files_upload")
async def on_admin_files_upload(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа", show_alert=True)

    agent_file_manager.set_waiting_for_file(callback.from_user.id)

    await callback.message.answer(
        "Отправь файл (документ) одним сообщением.\n\n"
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_files_list")
async def on_admin_files_list(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа", show_alert=True)

    files = await agent_file_manager.get_recent_files(limit=10, offset=0)
    
    if not files:
        await callback.message.answer("Файлов агента пока нет.")
        return await callback.answer()

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
    if callback.from_user.id != ADMIN_ID:
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
    if callback.from_user.id != ADMIN_ID:
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


@dp.message(CommandStart())
async def handle_start(message: Message):
    user_id = await db.save_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username
    )

    await message.answer(
        "Привет! Я AI-ассистент 👋\n"
        "Просто напиши мне вопрос, и я отвечу."
    )


@dp.message()
async def handle_message(message: Message):
    global AGENT_PROMPT

    if message.from_user.id == ADMIN_ID and message.from_user.id in WAITING_FOR_PROMPT:
        new_prompt = (message.text or "").strip()

        if not new_prompt:
            return await message.answer("Промпт не может быть пустым. Отправь текст ещё раз.")

        AGENT_PROMPT = new_prompt
        WAITING_FOR_PROMPT.remove(message.from_user.id)

        await db.set_setting("agent_prompt", AGENT_PROMPT)

        safe_prompt = html.escape(AGENT_PROMPT)

        await message.answer(
            "Промпт агента обновлён!\n\n"
            f"Текущий промпт:\n<code>{safe_prompt}</code>"
        )
        return

    if message.from_user.id == ADMIN_ID and agent_file_manager.is_waiting_for_file(message.from_user.id):
        response = await agent_file_manager.handle_file_upload(message, AGENT_VECTOR_STORE_ID)
        if response:
            await message.answer(response)
        return

    user_id = await db.save_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username
    )

    user_text = message.text or ""
    await db.save_message(user_id=user_id, role="user", content=user_text)

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

    await db.save_message(user_id=user_id, role="assistant", content=reply_text)
    await waiting_message.edit_text(reply_text, parse_mode=None)


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