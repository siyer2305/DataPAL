import sys
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv()

import os
import sqlite3
import html
from typing import List, Optional, AsyncGenerator, Dict
from io import BytesIO
import uuid

from fastapi import FastAPI, File, UploadFile, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from langgraph_sdk import get_client
from markupsafe import Markup

from data_handler import parse_file, push_to_db, DATABASE_PATH, list_tables, get_table_preview, delete_table

app = FastAPI(title="DataPAL: A Conversational Data Analysis Tool")
APP_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

def nl2br_filter(value: str) -> Markup:
    escaped_value = html.escape(value)
    return Markup(escaped_value.replace('\n', '<br>\n'))

templates.env.filters['nl2br'] = nl2br_filter

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

DB_PATH = DATABASE_PATH

try:
    langgraph_client = get_client(url="http://localhost:2024")
except Exception as e:
    print(f"Failed to initialize LangGraph client: {e}")
    langgraph_client = None

db_dir = os.path.dirname(DB_PATH)
if db_dir and not os.path.exists(db_dir):
    os.makedirs(db_dir)

@app.get("/", response_class=HTMLResponse)
async def main_page(request: Request):
    """Serves the main page with file upload and table management."""
    tables = list_tables(DB_PATH)
    return templates.TemplateResponse(
        "index.html", 
        {
            "request": request, 
            "tables": tables if tables is not None else [], 
            "db_path": DB_PATH, 
            "message": None, 
            "error": None
        }
    )

@app.post("/uploadfiles/")
async def create_upload_files(request: Request, files: List[UploadFile] = File(...)):
    """Handles file uploads, parsing, and pushing to database. Returns JSON.
    
    The frontend expects a JSON response with keys:
    - tables: list of current table names
    - upload_results: list of dicts, each with {filename, status, table_name?, error?, attempted_table_name?}
    - message: optional global success message string
    - error: optional global error message string
    """
    current_tables = list_tables(DB_PATH) # Get initial state of tables

    if not files:
        return JSONResponse(
            status_code=400,
            content={
                "tables": current_tables, 
                "upload_results": [], 
                "message": None, 
                "error": "No files were uploaded."
            }
        )

    if len(files) > 5: # This limit is now also enforced client-side, but good to keep backend check
        return JSONResponse(
            status_code=400,
            content={
                "tables": current_tables, 
                "upload_results": [], 
                "message": None, 
                "error": "You can upload a maximum of 5 files."
            }
        )

    results = []
    has_errors = False

    for file in files:
        if file.filename == "": # Handle case where empty file part is sent
            results.append(
                {
                    "filename": "Unknown (empty part)", 
                    "status": "Skipped", 
                    "error": "Empty file part received."
                }
            )
            has_errors = True
            continue  
        try:
            allowed_extensions = {".csv", ".xlsx", ".xls"}
            file_ext = os.path.splitext(file.filename)[1].lower()
            if file_ext not in allowed_extensions:
                results.append(
                    {
                        "filename": file.filename, 
                        "status": "Skipped", 
                        "error": f"Invalid file type: {file_ext}. Only CSV and Excel files are allowed."
                    }
                )
                has_errors = True
                continue

            await file.seek(0) 
            file_bytes = await file.read()
            file_like_object = BytesIO(file_bytes)
            file_like_object.name = file.filename 

            parsed_data = parse_file(file_like_object)

            if parsed_data is not None:
                table_name_base = os.path.splitext(file.filename)[0]
                success, actual_table_name, error_message = push_to_db(parsed_data, table_name_base, DB_PATH)
                if success:
                    results.append(
                        {
                            "filename": file.filename, 
                            "status": "Success", 
                            "table_name": actual_table_name
                        }
                    )
                else:
                    results.append(
                        {
                            "filename": file.filename, 
                            "status": "Failed to insert", 
                            "error": error_message, 
                            "attempted_table_name": actual_table_name
                        }
                    )
                    has_errors = True
            else:
                results.append(
                    {
                        "filename": file.filename, 
                        "status": "Failed to parse", 
                        "error": "File could not be parsed. Check format/content."
                    }
                )
                has_errors = True
        except Exception as e:
            results.append(
                {
                    "filename": file.filename, 
                    "status": "Error", 
                    "error": str(e)
                }
            )
            has_errors = True
        finally:
            await file.close()

    final_message = "File processing complete. See details below." if not has_errors else None
    final_error_message = "Some files could not be processed. See details below." if has_errors else None
    
    # Get updated list of tables after processing
    updated_tables = list_tables(DB_PATH)

    return JSONResponse(content={
        "tables": updated_tables if updated_tables is not None else [], 
        "upload_results": results, 
        "message": final_message,
        "error": final_error_message
    })

@app.get("/tables/{table_name}/preview", response_class=HTMLResponse)
async def preview_table_data(request: Request, table_name: str):
    """Displays a preview of the specified table."""
    try:
        preview_df = get_table_preview(table_name, DB_PATH)
        if preview_df is None: # Should not happen if get_table_preview raises error for non-existent table
             raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found or an error occurred during preview generation.")
        
        # Convert DataFrame to HTML, or pass it to the template to render
        # For simplicity, sending as list of dicts. Jinja can make a table.
        if not preview_df.empty:
            data_html = preview_df.to_html(classes="dataframe", index=False, border=0)
        else:
            data_html = f"<p class='empty-table-message'>Table '{table_name}' is empty.</p>"

        return templates.TemplateResponse("table_preview.html", {
            "request": request,
            "table_name": table_name,
            "data_html": data_html, # Send HTML directly
            "preview_data": preview_df.to_dict(orient="records") if not preview_df.empty else [],
            "columns": list(preview_df.columns)
        })
    except FileNotFoundError: # Raised by get_table_preview if DB doesn't exist
        raise HTTPException(status_code=404, detail=f"Database file not found at {DB_PATH}. Please upload files first.")
    except ValueError as ve: # Raised by get_table_preview if table doesn't exist
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        # Log the exception e for debugging
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred while previewing table '{table_name}': {str(e)}")


@app.post("/tables/{table_name}/delete", response_class=HTMLResponse)
async def delete_table_data(request: Request, table_name: str):
    """Deletes the specified table from the database."""
    # table_name is now correctly taken from the path
    try:
        success, message = delete_table(table_name, DB_PATH)
        if success:
            # Redirect to main page with a success message
            return RedirectResponse(url=f"/?message=Table '{table_name}' deleted successfully.", status_code=303)
        else:
            # Redirect to main page with an error message
            return RedirectResponse(url=f"/?error=Failed to delete table '{table_name}'. Reason: {message}", status_code=303)
    except Exception as e:
        # Log the exception e
        # Redirect with a generic error message
        return RedirectResponse(url=f"/?error=An unexpected error occurred while deleting table '{table_name}': {str(e)}", status_code=303)

# Chat Endpoints
def get_user_id(request: Request) -> str:
    """Get or create a user ID from cookies."""
    user_id = request.cookies.get("user_id")
    if not user_id:
        user_id = str(uuid.uuid4())
    return str(user_id)

@app.get("/new-chat-session", response_class=HTMLResponse, name="new_chat_session")
async def new_chat_session(request: Request):
    """Creates a new conversation thread and redirects to the chat page for it."""
    thread_id = str(uuid.uuid4())
    user_id = get_user_id(request)
    response = RedirectResponse(url=f"/chat/{thread_id}", status_code=302)
    response.set_cookie(key="user_id", value=user_id, httponly=True)
    response.set_cookie(key="thread_id", value=thread_id, httponly=True)
    return response

@app.get("/chat/{thread_id}", response_class=HTMLResponse)
async def chat_page(request: Request, thread_id: str):
    """Serves the chat page for a specific thread."""
    user_id = get_user_id(request) # Make sure user_id is available
    error_message_for_template = None
    
    if not langgraph_client:
        print("Error in chat_page: LangGraph client was not initialized.")
        error_message_for_template = "Chat service is not available (LangGraph client not initialized). Please check server logs and ensure the LangGraph server is running at http://localhost:2024."
        # Render chat.html with an error message
        return templates.TemplateResponse("chat.html", {
            "request": request,
            "thread_id": thread_id,
            "user_id": user_id,
            "db_path": DB_PATH, 
            "chat_error": error_message_for_template 
        })
    try:
        # Ensure thread exists, create if not.
        await langgraph_client.threads.create(
            thread_id=thread_id,
            if_exists="do_nothing",
            metadata={"user_id": user_id}
        )
    except Exception as e:
        print(f"Error interacting with LangGraph to ensure thread exists: {e}")
        error_message_for_template = f"Could not initialize chat session due to a LangGraph error: {str(e)}. Please ensure the LangGraph server is running at http://localhost:2024 and is accessible."

    # Pass thread_id, user_id, and any error to the template
    return templates.TemplateResponse("chat.html", {
        "request": request, 
        "thread_id": thread_id, 
        "user_id": user_id, 
        "db_path": DB_PATH,
        "chat_error": error_message_for_template
    })


# Helper to format chat messages for the template (similar to chatbot_app_reference.py)
# This is illustrative; your chat.html will dictate the exact structure needed.
def format_chat_message_html(msg: Dict[str, str], idx: str | int) -> str:
    """Renders a chat message to an HTML string.
    This is a simplified version. Your chat.html structure will determine this.
    """
    is_human = msg.get("type") == "human" or msg.get("role") == "user" # Accommodate different role keys
    
    bubble_class = "user-message" if is_human else "assistant-message"
    container_class = "message-container-user" if is_human else "message-container-assistant"
    
    # Escape content to prevent XSS, ensure newlines are preserved with CSS (white-space: pre-wrap)
    content = html.escape(str(msg.get("content", "")))

    return f"""
    <div id="chat-message-{idx}" class="message-container {container_class}">
        <div class="message-bubble {bubble_class}">
            {content}
        </div>
    </div>
    """

def assistant_message_placeholder_html(thread_id: str, run_id: str) -> str:
    """Generates HTML for the assistant's message placeholder with SSE."""
    content_id = f"assistant-content-{uuid.uuid4()}"
    
    # This HTML structure should match what chat.html expects for an assistant message,
    # with HTMX attributes for SSE.
    return f"""
    <div id="chat-message-assistant-{run_id}" class="message-container message-container-assistant sse-placeholder"
         hx-ext="sse"
         sse-connect="/chat/{thread_id}/get-message?run_id={run_id}"
         sse-swap="message"
         hx-target="#{content_id}"
         hx-swap="innerHTML">
        <div class="message-bubble assistant-message">
            <div id="{content_id}">
                <div class="typing-indicator">
                    <span></span><span></span><span></span>
                </div>
            </div>
        </div>
    </div>
    """

@app.post("/chat/{thread_id}/send-message")
async def send_chat_message(request: Request, thread_id: str):
    form_data = await request.form()
    user_message_content = form_data.get("msg", "") # Ensure 'msg' matches your form input name in chat.html

    if not user_message_content or user_message_content.isspace():
        return JSONResponse(content={"error": "Message cannot be empty"}, status_code=400)

    if not langgraph_client:
        # Return an error message in JSON format
        return JSONResponse(
            content={"error": "Chat service is not available (LangGraph client not initialized)."},
            status_code=503
        )
    # user_id = get_user_id(request) # Optional: Get user_id for logging or metadata if needed

    try:
        run = await langgraph_client.runs.create(
            thread_id=thread_id,
            assistant_id="agent",
            input={"messages": [{"role": "user", "content": user_message_content}]},
            stream_mode="messages" 
        )
        run_id = run["run_id"]
        
        return JSONResponse(content={"run_id": run_id})
    
    except Exception as e:
        print(f"Error creating run for agent: {e}")
        # Return an error message in JSON format
        return JSONResponse(
            content={"error": f"Error processing your message: {str(e)}"},
            status_code=500
        )

async def chat_message_generator(thread_id: str, run_id: str) -> AsyncGenerator[str, None]:
    """Streams assistant responses via SSE."""
    print(f"SSE_GENERATOR ({run_id}): Starting for thread {thread_id}. Will capture final assistant response.")
    if not langgraph_client:
        print(f"SSE_GENERATOR ({run_id}): LangGraph client not available.")
        yield f"event: error\ndata: {html.escape('LangGraph client not available.')}\n\n"
        yield f"event: close\ndata: {html.escape('Connection closed due to server error.')}\n\n"
        return

    latest_assistant_response_content = "" # Stores the latest full content of the assistant's response
    stream_event_count = 0
    message_event_sent_count = 0 # Should be 0 or 1

    try:
        async for chunk in langgraph_client.runs.join_stream(
            thread_id, run_id, stream_mode="messages" 
        ):
            stream_event_count += 1
            # print(f"SSE_GENERATOR ({run_id}): Chunk {stream_event_count}, Event: {chunk.event}, Raw Data: {chunk.data}") # Very verbose

            if chunk.event == "error":
                error_data = chunk.data if chunk.data else "Unknown stream error"
                print(f"SSE_GENERATOR ({run_id}): Yielding 'error' event due to stream error. Data: {error_data}")
                yield f"event: error\ndata: {html.escape(f'Stream error: {str(error_data)}')}\n\n"
                yield f"event: close\ndata: {html.escape('Connection closed due to stream error.')}\n\n"
                print(f"SSE_GENERATOR ({run_id}): SENT SSE 'error' and 'close' events to client due to LangGraph stream error.")
                return
            
            elif chunk.event == "close": 
                print(f"SSE_GENERATOR ({run_id}): Received 'close' event from langgraph stream itself (chunk {stream_event_count}). Not acting yet.")
                # This event signals the end of the LangGraph stream.
                # The final latest_assistant_response_content should be assembled by now.
                pass 
            
            elif chunk.event in ["messages", "messages/partial"] and chunk.data:
                event_type = chunk.event
                # print(f"SSE_GENERATOR ({run_id}): Processing '{event_type}' event (chunk {stream_event_count}).")

                current_chunk_ai_content = None
                # Iterate reversed to find the most recent AI message in this chunk's data
                for message_obj in reversed(chunk.data):
                    msg_content_data = None
                    is_ai_message = False

                    # Check for AIMessageChunk (streaming, .role)
                    if hasattr(message_obj, 'role') and message_obj.role == 'ai':
                        is_ai_message = True
                        msg_content_data = message_obj.content
                    # Check for AIMessage (complete message, .type)
                    elif hasattr(message_obj, 'type') and message_obj.type == 'ai':
                        is_ai_message = True
                        msg_content_data = message_obj.content
                    # Fallback for dict representation (e.g., if not using Pydantic models directly)
                    elif isinstance(message_obj, dict):
                        role = message_obj.get("role")
                        msg_type = message_obj.get("type") # Less common for 'ai' but for completeness
                        if role == "ai" or role == "assistant" or msg_type == "ai":
                            is_ai_message = True
                            msg_content_data = message_obj.get("content")
                    
                    if is_ai_message:
                        if isinstance(msg_content_data, str):
                            current_chunk_ai_content = msg_content_data
                            # print(f"SSE_GENERATOR ({run_id}):   Found string content: '{current_chunk_ai_content[:50]}...'")
                            break 
                        elif isinstance(msg_content_data, list):
                            # print(f"SSE_GENERATOR ({run_id}):   Found list content, processing blocks.")
                            temp_parts = []
                            for block_idx, content_block in enumerate(msg_content_data):
                                if isinstance(content_block, dict) and content_block.get("type") == "text" and "text" in content_block:
                                    text_part = content_block["text"]
                                    # print(f"SSE_GENERATOR ({run_id}):     Extracted text_part from block {block_idx}: '{text_part[:50]}...'")
                                    temp_parts.append(text_part)
                                elif isinstance(content_block, str): # Handle if a content block is just a string
                                    temp_parts.append(content_block)
                            current_chunk_ai_content = "".join(temp_parts)
                            break 
                
                if current_chunk_ai_content is not None:
                    latest_assistant_response_content = current_chunk_ai_content
                    # print(f"SSE_GENERATOR ({run_id}): Updated latest_assistant_response_content (len {len(latest_assistant_response_content)})")
            else:
                print(f"SSE_GENERATOR ({run_id}): Received unhandled/logging-only chunk event (chunk {stream_event_count}): {chunk.event}")

        # After the loop finishes, send the single, final message
        print(f"SSE_GENERATOR ({run_id}): LangGraph stream loop finished. Total chunks received: {stream_event_count}.")
        
        if latest_assistant_response_content.strip():
            print(f"SSE_GENERATOR ({run_id}): Sending final assistant message to client (length {len(latest_assistant_response_content)}).")
            yield f"event: message\ndata: {latest_assistant_response_content.replace(chr(10), '<br>')}\n\n"
            message_event_sent_count = 1
        else:
            print(f"SSE_GENERATOR ({run_id}): Final assistant message is empty. Not sending 'message' event.")

        print(f"SSE_GENERATOR ({run_id}): Total 'message' events sent to client: {message_event_sent_count}")
        yield f"event: close\ndata: {html.escape('Stream ended.')}\n\n"
        print(f"SSE_GENERATOR ({run_id}): SENT final SSE 'close' event to client.")

    except Exception as e:
        print(f"SSE_GENERATOR ({run_id}): CRITICAL Error during SSE streaming: {type(e).__name__} - {e}")
        import traceback
        print(traceback.format_exc())
        yield f"event: error\ndata: {html.escape(f'Error streaming response: {str(e)}')}\n\n"
        yield f"event: close\ndata: {html.escape('Connection closed due to server error.')}\n\n"
        print(f"SSE_GENERATOR ({run_id}): SENT SSE 'error' and 'close' events to client due to CRITICAL exception.")


@app.get("/chat/{thread_id}/get-message", response_class=StreamingResponse)
async def get_chat_message_stream(thread_id: str, run_id: Optional[str] = None):
    """SSE endpoint for streaming assistant responses."""
    if not run_id:
        # This case should ideally not be hit if the placeholder is always created with a run_id
        async def empty_generator():
            yield f"event: error\ndata: Missing run_id\n\n"
            yield f"event: close\ndata: Connection closed.\n\n"
            yield  # Keep pylint happy
        return StreamingResponse(empty_generator(), media_type="text/event-stream")

    return StreamingResponse(
        chat_message_generator(thread_id, run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    )
