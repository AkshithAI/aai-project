"""Configuration via environment variables with sensible defaults."""

import os
from dotenv import load_dotenv

load_dotenv()


# --- Database ---
CHECKPOINT_DB = os.getenv("CHECKPOINT_DB", "checkpoints.db")
TTL_DB = os.getenv("TTL_DB", "ttl.db")

# --- TTL ---
DEFAULT_TTL_SECONDS = int(os.getenv("DEFAULT_TTL_SECONDS", "3600"))  # 1 hour
SWEEPER_INTERVAL_SECONDS = int(os.getenv("SWEEPER_INTERVAL_SECONDS", "60"))

# --- LLM ---
LLM_MODEL = os.getenv("LLM_MODEL", "qwen/qwen3.8-27b")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# --- Server ---
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
