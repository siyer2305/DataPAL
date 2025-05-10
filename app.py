import streamlit as st
import pandas as pd
import sqlite3
import os
from data_handler import parse_file, push_to_db, DATABASE_PATH, list_tables, get_table_preview, delete_table

st.title("DataPAL: A Conversational Data Analysis Tool")

# Initialize session state for table preview
if 'preview_table_name' not in st.session_state:
    st.session_state.preview_table_name = None
if 'preview_df_data' not in st.session_state:
    st.session_state.preview_df_data = None

# Initialize session state for file uploader
if 'uploaded_files' not in st.session_state:
    st.session_state.uploaded_files = []

# Initialize session state for operation status messages
if 'operation_status' not in st.session_state:
    st.session_state.operation_status = None

# Initialize session state for chat interface
if 'show_chat_interface' not in st.session_state:
    st.session_state.show_chat_interface = False
if 'chat_messages' not in st.session_state: # To store chat messages
    st.session_state.chat_messages = []

st.header("Upload Files")

DB_PATH = DATABASE_PATH

# Determine the label for the file uploader
uploader_label = "Add More Files" if st.session_state.uploaded_files else "Choose CSV or Excel files (max 5 files)"

# Use the file_uploader widget with multiple files enabled
new_files = st.file_uploader(
    uploader_label,
    type=["csv", "xlsx", "xls"],
    accept_multiple_files=True,
    key="file_uploader"
)

# Handle file selection updates
if new_files is not None:
    # Get current filenames for comparison
    current_filenames = {f.name for f in st.session_state.uploaded_files}
    
    # Add new files that aren't already in the list
    for new_file in new_files:
        if new_file.name not in current_filenames:
            st.session_state.uploaded_files.append(new_file)
            current_filenames.add(new_file.name)

# Use the session state for further processing
uploaded_files = st.session_state.uploaded_files

# Add a clear button to remove all files
if uploaded_files:
    if st.button("Clear All Files"):
        st.session_state.uploaded_files = []
        st.rerun()

if uploaded_files:
    if len(uploaded_files) > 5:
        st.warning("You can upload a maximum of 5 files. Please select fewer files.")
        # Clear uploaded_files if too many are selected to prevent processing
        st.session_state.uploaded_files = [] # Clear from session state
        uploaded_files = [] 
    else:
        st.info(f"{len(uploaded_files)} file(s) selected. Click 'Process Files' to start.")
        for uploaded_file_obj in uploaded_files:
             st.write(f"Selected: {uploaded_file_obj.name}")

    if st.button("Process Files"):
        if not uploaded_files:
            st.warning("No files selected or too many files were selected. Please upload 1 to 5 files.")
        else:
            for uploaded_file in uploaded_files:
                if uploaded_file is not None: # This check might be redundant if uploaded_files is already filtered
                    file_details = {"FileName": uploaded_file.name, "FileType": uploaded_file.type, "FileSize": uploaded_file.size}
                    st.write(file_details)

                    # File type validation is already handled by st.file_uploader's 'type' parameter
                    # and also implicitly by the parser which returns None for unsupported types.
                    st.success(f"Processing {uploaded_file.name}...")
                    
                    # No temporary file saving needed anymore
                    # uploaded_file is a file-like object (BytesIO)

                    try:
                        st.write(f"Parsing file {uploaded_file.name}...")
                        # Pass the UploadedFile object directly to the parser
                        parsed_data = parse_file(uploaded_file) 
                        
                        if parsed_data is not None:
                            st.write(f"Parsed Data Preview for {uploaded_file.name} (first 5 rows):")
                            st.dataframe(parsed_data.head())

                            st.write(f"Inserting data from {uploaded_file.name} into database...")
                            
                            # Determine base name for the table from the original filename
                            table_name_base = os.path.splitext(uploaded_file.name)[0]
                            
                            # push_to_db now handles sanitization and DB interaction
                            success, actual_table_name, error_message = push_to_db(parsed_data, table_name_base, DB_PATH)
                            
                            if success:
                                st.success(f"Data from {uploaded_file.name} inserted successfully into table `{actual_table_name}` in database!")
                                
                                st.write(f"Preview of data from table `{actual_table_name}` (first 5 rows):")
                                # Need to connect to DB to show preview from the actual table
                                try:
                                    conn_preview = sqlite3.connect(DB_PATH)
                                    db_df = pd.read_sql_query(f'SELECT * FROM "{actual_table_name}" LIMIT 5', conn_preview)
                                    conn_preview.close()
                                    st.dataframe(db_df)
                                except Exception as e_preview:
                                    st.warning(f"Could not retrieve preview from database for table `{actual_table_name}`: {e_preview}")
                            else:
                                st.error(f"Failed to insert data from {uploaded_file.name} into database. Table name attempted: `{actual_table_name}`. Error: {error_message}")
                        else:
                            st.error(f"Failed to parse the file '{uploaded_file.name}'. Please check the file content, format, and ensure it is not empty or corrupted.")

                    except Exception as e:
                        st.error(f"An unexpected error occurred during processing of {uploaded_file.name}: {e}")
                    # No finally block for temp file removal needed anymore
                st.markdown("---") # Add a separator between processing of each file


else:
    st.info("Please upload a file to proceed.")

# Section for managing existing tables
st.header("Manage Existing Tables")

# Display operation status messages (e.g., from table deletion)
if 'operation_status' in st.session_state and st.session_state.operation_status:
    status = st.session_state.operation_status
    if status["type"] == "success":
        st.success(status["message"])
    elif status["type"] == "error":
        st.error(status["message"])
    # Clear the message after displaying it
    st.session_state.operation_status = None

current_tables = list_tables(DB_PATH)

if not current_tables:
    st.info("No tables found in the database. Upload some files to create tables.")
else:
    st.write("Select a table to manage:")
    
    # Determine a stable default index for selectbox
    default_index = 0
    if 'selected_table_manage' in st.session_state and st.session_state.selected_table_manage in current_tables:
        default_index = current_tables.index(st.session_state.selected_table_manage)
    elif current_tables: # if there are tables, and previous condition false, default to first
        st.session_state.selected_table_manage = current_tables[0]
    # If current_tables is empty, default_index remains 0, but selectbox won't be shown or options will be empty.

    # Define a callback for selectbox change to clear preview state
    def clear_preview_state_on_table_select():
        st.session_state.preview_table_name = None
        st.session_state.preview_df_data = None
        # We don't clear confirm_delete_table_name here, as selecting a new table
        # shouldn't interrupt a delete confirmation flow for a *different* table (if that scenario could occur).
        # The main logic will handle display based on current selected_table_manage.

    selected_table_manage = st.selectbox(
        "Available tables:",
        options=current_tables,
        index=default_index,
        key='selected_table_manage', 
        on_change=clear_preview_state_on_table_select, # Clear preview when selection changes
        label_visibility="collapsed"
    )

    if selected_table_manage:
        st.write(f"Actions for table: `{selected_table_manage}`")
        
        # Initialize confirmation state if not present
        if 'confirm_delete_table_name' not in st.session_state:
            st.session_state.confirm_delete_table_name = None

        # If a table is marked for deletion confirmation
        if st.session_state.get('confirm_delete_table_name') == selected_table_manage:
            st.warning(f"Are you sure you want to delete the table: `{selected_table_manage}`? This action cannot be undone.")
            c1, c2, c3 = st.columns([1,1,2]) # Give more space to cancel
            with c1:
                if st.button("Yes, Delete It", key=f"confirm_delete_yes_{selected_table_manage}", type="primary"):
                    success, returned_details = delete_table(selected_table_manage, DB_PATH)
                    if success:
                        final_message = ""
                        # Provide a clear, contextual success message
                        # Optionally append details if they are non-trivial and add value
                        if returned_details and returned_details.strip() and returned_details.lower() not in ["success", "ok", "done", "completed"]:
                            final_message += f"Details: {returned_details}"
                        st.session_state.operation_status = {"type": "success", "message": final_message}
                    else:
                        # Provide a clear, contextual error message
                        final_message = f"Failed to delete table `{selected_table_manage}`."
                        if returned_details and returned_details.strip():
                            final_message += f" Reason: {returned_details}"
                        else:
                            final_message += " An unspecified error occurred." # Fallback if no details
                        st.session_state.operation_status = {"type": "error", "message": final_message}

                    st.session_state.confirm_delete_table_name = None # Reset confirmation
                    st.session_state.preview_table_name = None # Clear preview state
                    st.session_state.preview_df_data = None   # Clear preview state
                    # Clear the selected table from session state to avoid errors if it was the one deleted
                    if 'selected_table_manage' in st.session_state and st.session_state.selected_table_manage == selected_table_manage:
                        del st.session_state.selected_table_manage # This forces selectbox to re-evaluate default
                    st.rerun()
            with c2:
                if st.button("Cancel", key=f"confirm_delete_no_{selected_table_manage}"):
                    st.session_state.confirm_delete_table_name = None # Reset confirmation
                    st.session_state.preview_table_name = None # Clear preview state
                    st.session_state.preview_df_data = None   # Clear preview state
                    st.rerun()
        else:
            # Show regular action buttons if no confirmation is active for this table
            col1, col2 = st.columns(2)
            with col1:
                if st.button(f"Preview Data from `{selected_table_manage}`", key=f"preview_{selected_table_manage}"):
                    # Action: Set session state variables for preview and rerun
                    st.session_state.preview_table_name = selected_table_manage
                    st.session_state.preview_df_data = get_table_preview(selected_table_manage, DB_PATH)
                    st.session_state.confirm_delete_table_name = None # Ensure not in delete mode
                    st.rerun() 
            
            with col2:
                if st.button(f"Delete Table `{selected_table_manage}`", key=f"delete_{selected_table_manage}"):
                    st.session_state.confirm_delete_table_name = selected_table_manage # Set table for confirmation
                    st.session_state.preview_table_name = None # Clear preview state if initiating delete
                    st.session_state.preview_df_data = None   # Clear preview state
                    st.rerun() # Rerun to show confirmation

        # Display full-width preview if active and not in delete confirmation for this table
        if st.session_state.get('preview_table_name') == selected_table_manage and \
           st.session_state.get('confirm_delete_table_name') != selected_table_manage:
            
            preview_df = st.session_state.get('preview_df_data')
            if preview_df is not None:
                st.markdown("---") 
                st.subheader(f"Data Preview: `{selected_table_manage}`")
                if not preview_df.empty:
                    st.dataframe(preview_df, use_container_width=True)
                else:
                    st.info(f"Table `{selected_table_manage}` is empty.")

st.markdown("---") # Separator before the new chat section button

# Check if we are showing the chat interface or the main data management view
if st.session_state.show_chat_interface:
    # --- CHAT INTERFACE VIEW ---
    st.header("Chat with Your Data")

    # Button to go back to the main data management view
    if st.button("⬅️ Back to Data Management"):
        st.session_state.show_chat_interface = False
        st.rerun()

    # Display existing chat messages
    for message in st.session_state.chat_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Placeholder for chat input and AI response
    if prompt := st.chat_input("Ask your data anything... (placeholder)"):
        # Add user message to chat history
        st.session_state.chat_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Placeholder AI response
        with st.chat_message("assistant"):
            st.markdown(f"Placeholder response: You asked '{prompt}'. The actual AI agent is not yet connected.")
        # Add AI response to chat history
        st.session_state.chat_messages.append({"role": "assistant", "content": f"Placeholder response: You asked '{prompt}'. The actual AI agent is not yet connected."})
        # No rerun needed here as chat_message and chat_input handle updates

else:
    # --- MAIN DATA MANAGEMENT VIEW ---
    # (The existing code for file upload and table management goes here)
    # We've already defined it above, so we just need to ensure the structure is correct.
    # The "Start Chatting" button will be part of this "else" block.

    st.header("Start Conversational Analysis")
    if st.button("💬 Start Chatting with your Data", type="primary"):
        # Check if there are any tables to chat with
        current_tables_for_chat_check = list_tables(DB_PATH)
        if not current_tables_for_chat_check:
            st.warning("Please upload some data and create tables before starting a chat.")
        else:
            st.session_state.show_chat_interface = True
            st.session_state.chat_messages = [] # Clear previous chat messages
            st.rerun()

st.sidebar.header("Instructions")
st.sidebar.info(
    f"1. Upload a CSV or Excel file.\n"
    f"2. The file will be parsed directly from memory.\n"
    f"3. Parsed data will be inserted into a local database in a table named after the file (sanitized)."
)

st.markdown("----")
st.markdown("🚀 Crafted with ❤️ by Shravan S | Powered by Streamlit")
