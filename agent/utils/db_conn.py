import os
from dotenv import load_dotenv
from langchain_community.utilities import SQLDatabase

load_dotenv()

class DBConnection:
    def __init__(self):
        self.DATABASE_PATH = os.getenv("DB_PATH")

    def get_db(self):
        return SQLDatabase.from_uri(f"sqlite:///{self.DATABASE_PATH}")

    def get_dialect(self):
        return self.get_db().dialect


if __name__ == "__main__":
    db = DBConnection().get_db()
    print(db.dialect)
    print(db.get_usable_table_names())