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
            # If file_input is a path, pandas reads it.
            # If file_input is a file-like object, pandas reads it directly.
            # Streamlit's UploadedFile provides a BytesIO-like interface.
            # For CSV, if it's bytes, it needs to be decoded or read appropriately.
            # Pandas read_csv can often handle BytesIO directly.
            if hasattr(file_input, 'getvalue') and isinstance(file_input.getvalue(), bytes):
                # Ensure the pointer is at the beginning if it's a BytesIO object
                if hasattr(file_input, 'seek'):
                    file_input.seek(0)
                # Attempt to decode if it's likely text-based CSV data in bytes
                try:
                    df = pd.read_csv(StringIO(file_input.getvalue().decode('utf-8')))
                except UnicodeDecodeError:
                    # If utf-8 fails, try with latin1 or let pandas infer
                    if hasattr(file_input, 'seek'):
                         file_input.seek(0)
                    df = pd.read_csv(file_input, encoding='latin1') # Or let pandas infer
            else: # It's a path or a text-based file-like object
                 if hasattr(file_input, 'seek'):
                    file_input.seek(0)
                 df = pd.read_csv(file_input)
            return df
        elif file_extension in ['.xls', '.xlsx']:
            # For excel, pandas needs a file path or a BytesIO object.
            # Streamlit's UploadedFile works well here.
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
        # If it's an UploadedFile that failed, it's good to show the type
        if hasattr(file_input, 'type'):
            print(f"Uploaded file type was: {file_input.type}")
        return None

if __name__ == '__main__':
    test_dir = r"C:\Users\siyer\DataPal\sample_data"
    
    print("Testing CSV parser...")
    csv_files = [f for f in os.listdir(test_dir) if f.endswith('.csv')]
    if csv_files:
        csv_path = os.path.join(test_dir, csv_files[0])
        print(f"Reading CSV file: {csv_files[0]}")
        df_csv = parse_file(csv_path)
        if df_csv is not None:
            print("First few records from CSV:")
            print(df_csv.head())
    else:
        print("No CSV files found in the directory")

    print("\nTesting Excel parser...")
    excel_files = [f for f in os.listdir(test_dir) if f.endswith(('.xlsx', '.xls'))]
    if excel_files:
        excel_path = os.path.join(test_dir, excel_files[0])
        print(f"Reading Excel file: {excel_files[0]}")
        df_excel = parse_file(excel_path)
        if df_excel is not None:
            print("First few records from Excel:")
            print(df_excel.head())
    else:
        print("No Excel files found in the directory")

    # Test with CSV BytesIO
    print("\nTesting CSV parser with BytesIO...")
    csv_content = "col_A,col_B\nval1,val2\nval3,val4"
    csv_bytes_io = BytesIO(csv_content.encode('utf-8'))
    csv_bytes_io.name = "sample_from_bytes.csv"
    df_csv_bytes = parse_file(csv_bytes_io)
    if df_csv_bytes is not None:
        print("Parsed CSV Data (from BytesIO):")
        print(df_csv_bytes)

    # Test with Excel BytesIO
    try:
        print("\nTesting Excel parser with BytesIO...")
        dummy_excel_df = pd.DataFrame({'Test_Col1': [100, 200], 'Test_Col2': ['x-val', 'y-val']})
        excel_bytes_io = BytesIO()
        dummy_excel_df.to_excel(excel_bytes_io, index=False, engine='openpyxl')
        excel_bytes_io.seek(0)
        excel_bytes_io.name = "sample_from_bytes.xlsx"
        
        df_excel_bytes = parse_file(excel_bytes_io)
        if df_excel_bytes is not None:
            print("Parsed Excel Data (from BytesIO):")
            print(df_excel_bytes)

    except ImportError:
        print("\nSkipping Excel BytesIO test: openpyxl not installed.")
    except Exception as e:
        print(f"\nError during Excel BytesIO test: {e}")

    # Test error cases
    print("\nTesting with a non-existent file path...")
    parse_file(os.path.join(test_dir, "non_existent.csv"))

    print("\nTesting with an unsupported file type...")
    unsupported_files = [f for f in os.listdir(test_dir) if f.endswith('.txt')]
    if unsupported_files:
        txt_path = os.path.join(test_dir, unsupported_files[0])
        parse_file(txt_path)
    else:
        print("No text files found for unsupported file type test")
    # if os.path.exists(csv_path): os.remove(csv_path)
    # if 'excel_path' in locals() and os.path.exists(excel_path): os.remove(excel_path)
    # if os.path.exists(txt_path): os.remove(txt_path)
    # if os.path.exists("test_data"): os.rmdir("test_data") # Careful if other files are there
    # print("\nCleaned up test files (commented out).") 