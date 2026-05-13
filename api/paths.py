import os

from config import BASE_DIR


PUBLIC_ROOT = BASE_DIR
PUBLIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")
