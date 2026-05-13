import logging

import db as dbm
from config import DB_PATH

from .cleanup import cleanup_expired_once


logger = logging.getLogger(__name__)


def run_once() -> None:
    conn = dbm.get_conn(DB_PATH)
    try:
        dbm.init_db(conn)
        cleanup_expired_once(conn)
    finally:
        conn.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger.info("Running expired session/media cleanup")
    run_once()
    logger.info("Cleanup finished")


if __name__ == "__main__":
    main()
