from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.types import Message

from .db import db
from .config import ADMIN_IDS

takeover_router = Router()


@takeover_router.message(CommandStart(deep_link=True))
async def admin_start(message: Message, command: CommandObject):
    payload = (command.args or "").strip()

    if message.chat.type != "private":
        return

    if not payload.startswith("chat_"):
        return

    admin_id = message.from_user.id
    if admin_id not in ADMIN_IDS:
        await message.answer("Нет прав открывать диалоги клиентов.")
        return

    try:
        user_id = int(payload.replace("chat_", "", 1))
    except ValueError:
        await message.answer("Некорректный ID клиента в ссылке.")
        return

    await db.set_conversation_mode(
        user_telegram_id=user_id,
        mode="admin",
        taken_by_admin_id=admin_id
    )

    await db.set_admin_active_chat(admin_id=admin_id, user_telegram_id=user_id)

    row = await db.fetchrow("SELECT id, username FROM users WHERE telegram_id = $1;", user_id)
    if not row:
        await message.answer(
            f"Диалог открыт с клиентом {user_id}, но истории пока нет.\n"
            "Команды: /close — закрыть диалог, /ai — вернуть ИИ клиенту"
        )
        return

    internal_user_id = row["id"]
    username = row["username"] or "без username"

    history = await db.fetch(
        """
        SELECT role, content, created_at
        FROM messages
        WHERE user_id = $1
        ORDER BY created_at DESC
        LIMIT 20;
        """,
        internal_user_id,
    )

    history = list(reversed(history))

    lines = [f"Открыт диалог с клиентом @{username} (id: {user_id})\n"]
    if not history:
        lines.append("История пуста.")
    else:
        for h in history:
            role = h["role"]
            content = h["content"]
            if role == "user":
                prefix = "Клиент"
            elif role == "assistant":
                prefix = "ИИ"
            elif role == "admin":
                prefix = "Админ"
            else:
                prefix = role
            lines.append(f"{prefix}: {content}")

    lines.append("\nПишите сюда, я пересилаю сообщение клиенту.")
    lines.append("Команды: /close — закрыть диалог, /ai — вернуть ИИ клиенту")

    await message.answer("\n".join(lines))


@takeover_router.message(Command("close"))
async def close_chat(message: Message):
    admin_id = message.from_user.id
    if admin_id not in ADMIN_IDS:
        return await message.answer("Нет прав.")

    user_id = await db.get_admin_active_chat(admin_id)
    if not user_id:
        return await message.answer("Нет активного диалога. Откройте через кнопку в лог-группе.")

    await db.clear_admin_active_chat(admin_id)

    await message.answer(
        f"Диалог с клиентом {user_id} закрыт для вас.\n"
        "Режим клиента не менял. Чтобы вернуть ИИ — команда /ai."
    )


@takeover_router.message(Command("ai"))
async def return_ai(message: Message):
    admin_id = message.from_user.id
    if admin_id not in ADMIN_IDS:
        return await message.answer("Нет прав.")

    user_id = await db.get_admin_active_chat(admin_id)
    if not user_id:
        return await message.answer("Нет активного диалога. Откройте через кнопку в лог-группе.")

    await db.set_conversation_mode(
        user_telegram_id=user_id,
        mode="ai",
        taken_by_admin_id=None,
    )

    await db.clear_admin_active_chat(admin_id)
    await message.answer(f"ИИ возвращён клиенту {user_id}.")

