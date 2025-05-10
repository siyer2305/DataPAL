import pandas as pd
import sqlite3
import os
import re
from dotenv import load_dotenv

load_dotenv()

def get_database_path(filename: str = os.getenv("DB_FILENAME")) -> str:
    """
    Gets the database path from environment variables and creates the directory if needed.
    
    Returns:
        str: The full path to the database file
    """
    db_directory = os.getenv("DB_PATH")
    database_filename = filename

    if db_directory:
        os.makedirs(db_directory, exist_ok=True)
        database_path = os.path.join(db_directory, database_filename)
    else:
        print(f"Warning: DB_DIR environment variable not found. Database '{database_filename}' will be created in the current directory: {os.path.abspath(database_filename)}")
        database_path = database_filename
    
    return database_path

DATABASE_PATH = get_database_path()

def list_tables(db_path: str = DATABASE_PATH) -> list[str]:
    """
    Lists all tables in the SQLite database.

    Args:
        db_path (str): Path to the SQLite database file.

    Returns:
        list[str]: A list of table names.
    """
    tables = []
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
    except sqlite3.Error as e:
        print(f"SQLite error while listing tables: {e}")
    return tables

def get_table_preview(table_name: str, db_path: str = DATABASE_PATH, limit: int = 5) -> pd.DataFrame | None:
    """
    Fetches a preview (first N rows) of a table from the SQLite database.

    Args:
        table_name (str): The name of the table to preview.
        db_path (str): Path to the SQLite database file.
        limit (int): The maximum number of rows to fetch.

    Returns:
        pd.DataFrame | None: A DataFrame with the preview data, or None if an error occurs or table not found.
    """
    try:
        conn = sqlite3.connect(db_path)
        # Sanitize table_name just in case, though it should be from a trusted list
        # However, direct SQL construction with f-string is generally risky.
        # Using parameters for table names directly is not supported by sqlite3 for FROM clause.
        # We rely on table_name being from a list of existing tables.
        query = f'SELECT * FROM "{table_name}" LIMIT {limit}'
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df
    except sqlite3.Error as e:
        print(f"SQLite error while getting table preview for '{table_name}': {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred while getting table preview for '{table_name}': {e}")
        return None

def delete_table(table_name: str, db_path: str = DATABASE_PATH) -> tuple[bool, str]:
    """
    Deletes a table from the SQLite database.

    Args:
        table_name (str): The name of the table to delete.
        db_path (str): Path to the SQLite database file.

    Returns:
        tuple[bool, str]: (success_status, message)
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # Ensure table name is quoted for safety, similar to get_table_preview
        cursor.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        conn.commit()
        conn.close()
        return True, f"Table '{table_name}' deleted successfully."
    except sqlite3.Error as e:
        error_msg = f"SQLite error while deleting table '{table_name}': {e}"
        print(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"An unexpected error occurred while deleting table '{table_name}': {e}"
        print(error_msg)
        return False, error_msg

def sanitize_name(name: str, is_table: bool = True) -> str:
    """
    Sanitizes a string to be a valid SQL table or column name.
    - Replaces non-alphanumeric characters (excluding underscores) with underscores.
    - Ensures the name doesn't start with a digit (prepends 'tbl_' for tables, 'col_' for columns).
    - Replaces multiple consecutive underscores with a single underscore.
    - Strips leading/trailing underscores.
    - Handles empty names by returning a default ('generic_table' or 'generic_column').
    """
    
    # Replace non-alphanumeric (excluding underscore) with underscore
    name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    
    # Replace multiple underscores with a single one
    name = re.sub(r'_+', '_', name)
    
    # Strip leading/trailing underscores
    name = name.strip('_')
    
    # If name becomes empty after sanitization, provide a default
    if not name:
        return "generic_table" if is_table else "generic_column"
        
    # Prepend if it starts with a digit or is a reserved keyword (simple check for digit for now)
    # SQLite allows names to start with underscore, but some other DBs or tools might not like it.
    # For wider compatibility, we can enforce starting with a letter.
    if not name[0].isalpha() and name[0] != '_': # if not starting with letter or underscore
        prefix = "tbl_" if is_table else "col_"
        name = prefix + name
    elif name[0].isdigit(): # If starts with digit (even if underscore was allowed before)
        prefix = "tbl_" if is_table else "col_"
        name = prefix + name

    # A more robust check for SQL keywords could be added if necessary
    # For now, this covers common issues.
    return name

def push_to_db(df: pd.DataFrame, table_name_base: str, db_path: str = DATABASE_PATH) -> tuple[bool, str | None, str | None]:
    """
    Pushes a pandas DataFrame to a specified SQLite database table.

    Args:
        df (pd.DataFrame): The DataFrame to push.
        table_name_base (str): The base name for the table (e.g., original filename without extension).
        db_path (str): Path to the SQLite database file. Defaults to DATABASE_NAME.

    Returns:
        tuple[bool, str | None, str | None]: (success_status, actual_table_name, error_message)
    """

    if df.empty:
        return False, None, "Input DataFrame is empty. Nothing to push."

    actual_table_name = sanitize_name(table_name_base, is_table=True)
    
    # Sanitize column names
    # Create a copy to avoid SettingWithCopyWarning if df is a slice
    df_renamed = df.copy()
    clean_columns = {col: sanitize_name(col, is_table=False) for col in df_renamed.columns}
    df_renamed.rename(columns=clean_columns, inplace=True)

    try:
        conn = sqlite3.connect(db_path)
        # Using if_exists='replace' as per previous logic. Change to 'append' or 'fail' if needed.
        df_renamed.to_sql(actual_table_name, conn, if_exists='replace', index=False)
        conn.commit()
        conn.close()
        return True, actual_table_name, None
    except sqlite3.Error as e_sqlite:
        error_msg = f"SQLite error during database operation: {e_sqlite}"
        print(error_msg)
        return False, actual_table_name, error_msg # Return actual_table_name even on error for context
    except Exception as e:
        error_msg = f"An unexpected error occurred: {e}"
        print(error_msg)
        return False, actual_table_name, error_msg

if __name__ == '__main__':
    
    # Test reading from actual database
    print("\nChecking contents of production database...")
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        # Get list of all tables
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
            
        if not tables:
            print("No tables found in database.")
        else:
            print(f"Found {len(tables)} tables:")
            for table in tables:
                table_name = table[0]
                print(f"\nTable: {table_name}")
                # Get row count
                cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
                row_count = cursor.fetchone()[0]
                print(f"Number of rows: {row_count}")
                # Show first few rows
                df = pd.read_sql_query(f'SELECT * FROM "{table_name}" LIMIT 5', conn)
                print("\nFirst 5 rows:")
                print(df)
            conn.close()
    except Exception as e:
            print(f"Error accessing production database: {e}")