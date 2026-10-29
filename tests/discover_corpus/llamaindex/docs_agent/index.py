import os
from functools import lru_cache

from llama_index.core import StorageContext, load_index_from_storage

PERSIST_DIR = os.getenv("DOCS_INDEX_DIR", "./storage/docs")


@lru_cache(maxsize=1)
def get_query_engine():
    storage = StorageContext.from_defaults(persist_dir=PERSIST_DIR)
    index = load_index_from_storage(storage)
    return index.as_query_engine(similarity_top_k=4)
