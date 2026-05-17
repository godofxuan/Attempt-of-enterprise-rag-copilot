import _bootstrap  # noqa: F401

from app.config import get_settings

settings = get_settings()

print("chat_model =", settings.chat_model)
print("embedding_model =", settings.embedding_model)
print("base_url =", settings.llm_base_url)
print("chunk_size =", settings.chunk_size)
print("sqlite_path =", settings.sqlite_path)
