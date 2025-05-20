import pandas as pd
import os
from io import BytesIO, StringIO
import openpyxl
from dotenv import load_dotenv

load_dotenv()

def parse_file(file_input) -> pd.DataFrame | None:
    """
    Parses a CSV or Excel file from a file path or a file-like object into a pandas DataFrame.

    Args:
        file_input: Either a string path to the CSV or Excel file, 
                    or a file-like object (e.g., BytesIO, StringIO, Streamlit's UploadedFile).

    Returns:
        pd.DataFrame: A pandas DataFrame containing the parsed data, 
                      or None if the file type is unsupported or an error occurs.
    """
    file_extension = None
    original_filename = None

    if hasattr(file_input, 'name'): # Check if it's a file-like object with a 'name' attribute (like Streamlit's UploadedFile)
        original_filename = file_input.name
        file_extension = os.path.splitext(original_filename)[1].lower()
    elif hasattr(file_input, 'filename'): # Check for FastAPI's UploadFile
        original_filename = file_input.filename
        file_extension = os.path.splitext(original_filename)[1].lower()
    elif isinstance(file_input, str):
        original_filename = file_input
        file_extension = os.path.splitext(file_input)[1].lower()
    else:
        print("Error: Input type not recognized. Must be a file path or a file-like object with a 'name' attribute.")
        return None

    try:
        if file_extension == '.csv':
            if hasattr(file_input, 'getvalue') and isinstance(file_input.getvalue(), bytes):
                if hasattr(file_input, 'seek'):
                    file_input.seek(0)
                try:
                    df = pd.read_csv(StringIO(file_input.getvalue().decode('utf-8')))
                except UnicodeDecodeError:
                    if hasattr(file_input, 'seek'):
                         file_input.seek(0)
                    df = pd.read_csv(file_input, encoding='latin1') # Or let pandas infer
            else: # It's a path or a text-based file-like object
                 if hasattr(file_input, 'seek'):
                    file_input.seek(0)
                 df = pd.read_csv(file_input)
            return df
        elif file_extension in ['.xls', '.xlsx']:
            if hasattr(file_input, 'seek'):
                file_input.seek(0)
            df = pd.read_excel(file_input, engine='openpyxl' if file_extension == '.xlsx' else None)
            return df
        else:
            print(f"Unsupported file type: {file_extension} for file {original_filename}")
            return None
    except FileNotFoundError: # This error is relevant if file_input was a path string
        print(f"Error: File not found at {original_filename}")
        return None
    except pd.errors.EmptyDataError:
        print(f"Error: The file {original_filename} is empty.")
        return None
    except Exception as e:
        print(f"An error occurred while parsing {original_filename}: {e}")
        if hasattr(file_input, 'type'):
            print(f"Uploaded file type was: {file_input.type}")
        return None
