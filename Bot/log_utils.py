import os
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, User
from dotenv import load_dotenv

load_dotenv()

BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip().lstrip("@")
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID", "0"))


async def send_ai_log(
    bot: Bot,
    user: User,
    user_message: str,
    ai_answer: str,
) -> None:

    if LOG_CHAT_ID == 0:
        return

    username = user.username or "без username"

    text = (
        f"Клиент: @{username} (id: {user.id})\n"
        f"Сообщение: «{user_message}»\n\n"
        f"Ответ ИИ:\n{ai_answer}"
    )

    if not BOT_USERNAME:
        keyboard = None
    else:
        open_url = f"https://t.me/{BOT_USERNAME}?start=chat_{user.id}"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Перейти в диалог", url=open_url)]]
        )

    await bot.send_message(
        chat_id=LOG_CHAT_ID,
        text=text,
        reply_markup=keyboard,
    )


async def send_admin_user_message(bot: Bot, user: User, user_message: str) -> None:
    if LOG_CHAT_ID == 0:
        return

    username = user.username or "без username"

    text = (
        "Сообщение от клиента (ручной режим)\n"
        f"Клиент: @{username} (id: {user.id})\n"
        f"Сообщение: «{user_message}»"
    )

    await bot.send_message(
        chat_id=LOG_CHAT_ID,
        text=text,
    )