## get all .env variables
import os
from dotenv import load_dotenv

load_dotenv()
hf_token = os.getenv("HF_TOKEN")
llamaparse_api = os.getenv("LLAMAPARSE_API")
db_url = os.getenv("DB_URL")
voyage_api_key = os.getenv("VOYAGE_API_KEY")
