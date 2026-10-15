import os
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("RAG_BASE_URL", "http://rag.test")
os.environ.setdefault("RAG_SEARCH_API_KEY", "test-search-key")
os.environ.setdefault("RAG_ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("AI_PROVIDER", "openai")
os.environ.setdefault("OPENAI_BASE_URL", "http://llm.test/v1")
os.environ.setdefault("OPENAI_API_KEY", "test-llm-key")
os.environ.setdefault("OPENAI_MODEL", "test-model")
os.environ.setdefault("PRODUCT_TIMEZONE_OFFSET", "+07:00")
os.environ.setdefault("PRODUCT_CHAT_PAGE_SIZE", "10")
os.environ.setdefault("PRODUCT_CANDIDATE_PAGE_SIZE", "50")
