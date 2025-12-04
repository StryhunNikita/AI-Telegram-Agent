import os
import html
from typing import Optional, Set
from aiogram.types import Message

from .llm import upload_file_to_vector_store
from .llm import delete_file_from_vector_store
from .db import db


class AgentFileManager:
    def __init__(self):
        self.waiting_for_file_upload: Set[int] = set()
    
    def is_waiting_for_file(self, user_id: int) -> bool:
        return user_id in self.waiting_for_file_upload
    
    def set_waiting_for_file(self, user_id: int) -> None:
        self.waiting_for_file_upload.add(user_id)
    
    def clear_waiting_for_file(self, user_id: int) -> None:
        self.waiting_for_file_upload.discard(user_id)
    

    async def handle_file_upload(self, message: Message, vector_store_id: Optional[str]) -> Optional[str]:
        if vector_store_id is None:
            return "Vector store агента не инициализирован. Обратись к разработчику."

        if not message.document:
            return "Пожалуйста, отправь файл как документ."
        
        doc = message.document
        filename = doc.file_name or "document"
        file_id = doc.file_id
        mime_type = doc.mime_type
        file_size = doc.file_size

        try:
            tg_file = await message.bot.get_file(file_id)
            file_path = tg_file.file_path

            # /tmp на Mac 
            tmp_dir = "/tmp"
            os.makedirs(tmp_dir, exist_ok=True)
            save_path = os.path.join(tmp_dir, filename)

            await message.bot.download_file(file_path, save_path)
        except Exception as e:
            print("Ошибка при скачивании файла:", e)
            return "Ошибка при загрузке файла из Telegram."

        openai_file_id = None
        try:
            openai_file_id = await upload_file_to_vector_store(save_path, vector_store_id)
            if not openai_file_id:
                return "Не удалось загрузить файл в vector store."
        finally:
            try:
                os.remove(save_path)
            except OSError:
                pass

        await db.save_agent_file(
            filename=filename,
            telegram_file_id=file_id,
            openai_file_id=openai_file_id,   
            vector_store_id=vector_store_id,
            mime_type=mime_type,
            file_size=file_size,
        )

        self.clear_waiting_for_file(message.from_user.id)
        return (
            f"Файл <b>{html.escape(filename)}</b> сохранён.\n\n"
            f"Добавлен в векторное хранилище агента."
        )
    
    async def format_files_list(self, limit: int = 10, offset: int = 0) -> str:
        files = await db.list_agent_files(limit=limit, offset=offset)
        
        if not files:
            return "Файлов агента пока нет."
        
        lines = []
        for row in files:
            created = row["created_at"].strftime("%Y-%m-%d %H:%M")
            lines.append(f"{row['id']}. <b>{html.escape(row['filename'])}</b> ({created})")
        
        return "Сохранённые файлы агента:\n\n" + "\n".join(lines)
    

    async def get_file_info(self, file_id: int) -> Optional[dict]:
        return await db.get_agent_file(file_id)
    

    async def delete_file(self, file_id: int) -> bool:
        row = await db.get_agent_file(file_id)
        if not row:
            return False

        openai_file_id = row["openai_file_id"]
        vector_store_id = row["vector_store_id"]

        if openai_file_id and vector_store_id:
            await delete_file_from_vector_store(
                vector_store_id=vector_store_id,
                file_id=openai_file_id,
            )

        await db.delete_agent_file(file_id)
        return True

    async def get_recent_files(self, limit: int = 10, offset: int = 0):
        return await db.list_agent_files(limit=limit, offset=offset)


agent_file_manager = AgentFileManager()
