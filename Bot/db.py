import os
import asyncpg
from typing import Optional
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 5432)),
            min_size=1,
            max_size=5,
        )
    
    async def disconnect(self) -> None:
        if self.pool is not None:
            await self.pool.close()

    async def fetchrow(self, query: str, *args):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetch(self, query: str, *args):
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def execute(self, query: str, *args):
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args) 


    async def create_table(self) -> None:
        async with self.pool.acquire() as conn:
            await self.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT UNIQUE NOT NULL,
                    username TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )

            await self.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,            -- 'user' / 'assistant' / 'system'
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )

            await self.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    user_telegram_id BIGINT PRIMARY KEY,
                    mode TEXT NOT NULL DEFAULT 'ai',         
                    taken_by_admin_id BIGINT,               
                    taken_at TIMESTAMPTZ                    
                );
                """
            )

            await self.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_sessions (
                    admin_id BIGINT PRIMARY KEY,
                    active_user_telegram_id BIGINT,
                    updated_at TIMESTAMP DEFAULT NOW()
                );
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_files (
                    id SERIAL PRIMARY KEY,
                    filename TEXT NOT NULL,
                    telegram_file_id TEXT NOT NULL,
                    openai_file_id TEXT,
                    vector_store_id TEXT,
                    mime_type TEXT,
                    file_size BIGINT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )


    async def save_user(self, telegram_id: int, username: Optional[str]):
        row = await self.fetchrow(
            "SELECT id FROM users WHERE telegram_id = $1;",
            telegram_id,
        )

        if row:
            return row["id"]

        row = await self.fetchrow(
            """
            INSERT INTO users (telegram_id, username)
            VALUES ($1, $2)
            RETURNING id;
            """,
            telegram_id,
            username,
        )
        return row["id"]

    async def save_message(self, user_id: int, role: str, content: str) -> None:
        await self.execute(
            """
            INSERT INTO messages (user_id, role, content)
            VALUES ($1, $2, $3);
            """,
            user_id,
            role,
            content,
        )

    async def search_messages(self, user_id: int, query: str, limit: int = 5):
        return await self.fetch(
            """
            SELECT content
            FROM messages
            WHERE user_id = $1
              AND content ILIKE '%' || $2 || '%'
            ORDER BY created_at DESC
            LIMIT $3;
            """,
            user_id,
            query,
            limit,
        )

    async def get_user_messages(self, user_id: int, limit: int = 20) -> list:
        return await self.fetch(
            """
            SELECT role, content
            FROM messages
            WHERE user_id = $1
            ORDER BY created_at ASC
            LIMIT $2;
            """,
            user_id,
            limit,
        )

    async def get_setting(self, key: str) -> Optional[str]:
        query = "SELECT value FROM settings WHERE key = $1"
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, key)
        if row:
            return row["value"]
        return None

    async def set_setting(self, key: str, value: str) -> None:
        query = """
            INSERT INTO settings (key, value)
            VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, key, value)

    async def count_messages(self, user_id: int) -> int:
        row = await self.fetchrow(
            "SELECT COUNT(*) AS count FROM messages WHERE user_id = $1;",
            user_id,
        )
        return row["count"]

    async def delete_old_messages(self, user_id: int, extra: int) -> None:
        await self.execute(
            """
            DELETE FROM messages
            WHERE id IN (
                SELECT id
                FROM messages
                WHERE user_id = $1
                ORDER BY created_at ASC
                LIMIT $2
            );
            """,
            user_id,
            extra,
        )

    async def save_agent_file(
        self,
        *,
        filename: str,
        telegram_file_id: str,
        openai_file_id: Optional[str] = None,
        vector_store_id: Optional[str] = None,
        mime_type: Optional[str] = None,
        file_size: Optional[int] = None,
    ) -> int:
        row = await self.fetchrow(
            """
            INSERT INTO agent_files (filename, telegram_file_id, openai_file_id,
                                     vector_store_id, mime_type, file_size)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id;
            """,
            filename,
            telegram_file_id,
            openai_file_id,
            vector_store_id,
            mime_type,
            file_size,
        )
        return row["id"]

    async def list_agent_files(self, limit: int = 20, offset: int = 0):
        return await self.fetch(
            """
            SELECT id, filename, created_at
            FROM agent_files
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2;
            """,
            limit,
            offset,
        )

    async def get_agent_file(self, file_id: int):
        return await self.fetchrow(
            """
            SELECT *
            FROM agent_files
            WHERE id = $1;
            """,
            file_id,
        )

    async def delete_agent_file(self, file_id: int) -> None:
        await self.execute(
            """
            DELETE FROM agent_files
            WHERE id = $1;
            """,
            file_id,
        )

    async def count_agent_files(self) -> int:
        row = await self.fetchrow("SELECT COUNT(*) AS c FROM agent_files;")
        return row["c"] if row else 0


    async def set_conversation_mode(
        self,
        user_telegram_id: int,
        mode: str,
        taken_by_admin_id: Optional[int] = None,
    ) -> None:

        query = """
        INSERT INTO conversations (user_telegram_id, mode, taken_by_admin_id, taken_at)
        VALUES ($1, $2, $3, CASE WHEN $2 = 'admin' THEN NOW() ELSE NULL END)
        ON CONFLICT (user_telegram_id) 
        DO UPDATE SET
            mode = EXCLUDED.mode,
            taken_by_admin_id = EXCLUDED.taken_by_admin_id,
            taken_at = CASE WHEN EXCLUDED.mode='admin' THEN NOW() ELSE NULL END;
        """

        await self.pool.execute(query, user_telegram_id, mode, taken_by_admin_id)


    async def set_admin_active_chat(self, admin_id: int, user_telegram_id: int) -> None:
        query = """
        INSERT INTO admin_sessions (admin_id, active_user_telegram_id, updated_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (admin_id)
        DO UPDATE SET active_user_telegram_id = EXCLUDED.active_user_telegram_id,
                    updated_at = NOW();
        """
        await self.pool.execute(query, admin_id, user_telegram_id)


    async def get_admin_active_chat(self, admin_id: int) -> Optional[int]:
        query = """
        SELECT active_user_telegram_id
        FROM admin_sessions
        WHERE admin_id = $1;
        """
        row = await self.pool.fetchrow(query, admin_id)
        return row["active_user_telegram_id"] if row else None


    async def clear_admin_active_chat(self, admin_id: int) -> None:
        query = "UPDATE admin_sessions SET active_user_telegram_id = NULL, updated_at = NOW() WHERE admin_id = $1;"
        await self.pool.execute(query, admin_id)


    async def get_conversation_state(self, user_telegram_id: int) -> tuple[Optional[str], Optional[int], Optional[datetime]]:
        query = """
        SELECT mode, taken_by_admin_id, taken_at
        FROM conversations
        WHERE user_telegram_id = $1;
        """
        row = await self.pool.fetchrow(query, user_telegram_id)
        if not row:
            return None, None, None
        return row["mode"], row["taken_by_admin_id"], row["taken_at"]


db = Database()
