import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    TRELLO_API_KEY = os.getenv("TRELLO_API_KEY")
    TRELLO_TOKEN = os.getenv("TRELLO_TOKEN")
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    
    # Proje Ayarları
    GITHUB_REPO_NAME = "gorkemtosuntw/doc-gen-mvp"
    REPO_URL = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO_NAME}.git"
    
    # Trello ID'leri
    LIST_IN_PROGRESS = "691d9d7f9faff31f3cc13819"
    LIST_REVIEW = "691d9d7f9faff31f3cc1381a"
    BOT_USERNAME = "gorkemt1"