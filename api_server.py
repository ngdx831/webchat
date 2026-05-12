"""Thin entrypoint for the Flask API server. Business logic lives in `api/`."""
from api.app import main


if __name__ == "__main__":
    main()
