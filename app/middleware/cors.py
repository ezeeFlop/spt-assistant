from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings # Assuming you'll add allowed origins to config

# In a real application, you would likely pull allowed_origins from your settings/config
# For development, allowing all origins might be acceptable, but be more restrictive in production.
ALLOWED_ORIGINS = [
    "http://localhost",
    "http://localhost:3000", # Common port for React dev servers
    "http://localhost:5173", # Common port for Vite dev servers
    "http://127.0.0.1",      # ADDED
    "http://127.0.0.1:3000", # ADDED
    "http://127.0.0.1:5173", # ADDED
    # Add your frontend production URL here
]

# If you want to allow all origins (not recommended for production):
# ALLOWED_ORIGINS_TEMP_ALL = ["*"] # REVERTED

def add_cors_middleware(app):
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS, # REVERTED (was ALLOWED_ORIGINS_TEMP_ALL)
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    ) 