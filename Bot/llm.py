import os
import asyncio
from typing import Optional, Sequence
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Не задан OPENAI_API_KEY.")

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,  
)

def _create_vector_store_sync(name: str) -> str:
    vector_store = client.vector_stores.create(name=name)
    print(f"Vector store создан: {vector_store.id} ({name})")
    return vector_store.id


async def create_vector_store(name: str) -> str:
    return await asyncio.to_thread(_create_vector_store_sync, name)


def _ask_gpt_sync(
    user_text: str,
    system_prompt: str,
    vector_store_id: Optional[str] = None,
) -> str:
    try:
        kwargs = dict(
            model=OPENAI_MODEL,
            input=user_text,
            instructions=system_prompt,
        )

        if vector_store_id:
            kwargs["tools"] = [
                {
                    "type": "file_search",
                    "vector_store_ids": [vector_store_id],
                }
            ]

        response = client.responses.create(**kwargs)

        if hasattr(response, "output_text") and response.output_text:
            return response.output_text.strip()

        return str(response)

    except Exception as e:
        print("OpenAI API error:", repr(e))
        return "Ошибка при обращении к модели."


async def ask_assistant(
    user_text: str,
    system_prompt: str,
    vector_store_id: Optional[str] = None,
) -> str:
    return await asyncio.to_thread(_ask_gpt_sync, user_text, system_prompt, vector_store_id)



def _upload_file_to_vector_store_sync(
    filepath: str,
    vector_store_id: str,
) -> Optional[str]:
    try:
        with open(filepath, "rb") as f:
            file_obj = client.files.create(
                file=f,
                purpose="assistants",
            )

        client.vector_stores.files.create_and_poll(
            vector_store_id=vector_store_id,
            file_id=file_obj.id,
        )

        return file_obj.id
    except Exception as e:
        print("OpenAI upload_to_vector_store error:", repr(e))
        return None


async def upload_file_to_vector_store(
    filepath: str,
    vector_store_id: str,
) -> Optional[str]:
    return await asyncio.to_thread(
        _upload_file_to_vector_store_sync,
        filepath,
        vector_store_id,
    )


def _delete_file_from_vector_store_sync(
    vector_store_id: str,
    file_id: str,
) -> None:
    try:
        client.vector_stores.files.delete(
            vector_store_id=vector_store_id,
            file_id=file_id,
        )
    except Exception as e:
        print("Error deleting from vector store:", repr(e))

    try:
        client.files.delete(file_id=file_id)
    except Exception as e:
        print("Error deleting OpenAI file:", repr(e))


async def delete_file_from_vector_store(
    vector_store_id: str,
    file_id: str,
) -> None:
    await asyncio.to_thread(
        _delete_file_from_vector_store_sync,
        vector_store_id,
        file_id,
    )
