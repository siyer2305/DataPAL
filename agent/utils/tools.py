import os
from dotenv import load_dotenv
from uuid import uuid4
from typing import Literal
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit
from langgraph.prebuilt import ToolNode

from .state import State
from .db_conn import DBConnection

load_dotenv()

llm = ChatAnthropic(
    model_name="claude-3-7-sonnet-latest",
    api_key=os.getenv("ANTHROPIC_API_KEY", ""),
    temperature=0.0,
    max_tokens=4096,
)

db = DBConnection().get_db()
db_dialect = DBConnection().get_dialect()

toolkit = SQLDatabaseToolkit(
    db=db,
    llm=llm,
)
tools = toolkit.get_tools()

get_schema_tool = next(tool for tool in tools if tool.name == "sql_db_schema")
get_schema_node = ToolNode([get_schema_tool], name="get_schema")

run_query_tool = next(tool for tool in tools if tool.name == "sql_db_query")
run_query_node = ToolNode([run_query_tool], name="run_query")

def list_tables(state: State):
    tool_call = {
        "name": "sql_db_list_tables",
        "args": {},
        "id": str(uuid4()),
        "type": "tool_call",
    }
    tool_call_message = AIMessage(content="", tool_calls=[tool_call])

    list_tables_tool = next(tool for tool in tools if tool.name == "sql_db_list_tables")
    tool_message = list_tables_tool.invoke(tool_call)
    response = AIMessage(f"Available tables: {tool_message.content}")

    return {"messages": [tool_call_message, tool_message, response]}

def call_get_schema(state: State):
    schema_llm = llm.bind_tools([get_schema_tool], tool_choice="any")
    response = schema_llm.invoke(state["messages"])

    return {"messages": [response]}

def generate_query(state: State, config: RunnableConfig):
    generate_query_system_prompt = config["configurable"].get("generate_query_system_prompt", "")
    system_message = {
        "role": "system",
        "content": generate_query_system_prompt.format(dialect=db_dialect, top_k=5),
    }
    # We do not force a tool call here, to allow the model to
    # respond naturally when it obtains the solution.
    query_run_llm = llm.bind_tools([run_query_tool])
    response = query_run_llm.invoke([system_message] + state["messages"])

    return {"messages": [response]}

def check_query(state: State, config: RunnableConfig):
    check_query_system_prompt = config["configurable"].get("check_query_system_prompt", "")
    system_message = {
        "role": "system",
        "content": check_query_system_prompt.format(dialect=db_dialect),
    }

    # Generate an artificial user message to check
    tool_call = state["messages"][-1].tool_calls[0]
    user_message = {"role": "user", "content": tool_call["args"]["query"]}
    query_checker_llm = llm.bind_tools([run_query_tool], tool_choice="any")
    response = query_checker_llm.invoke([system_message, user_message])
    response.id = state["messages"][-1].id

    return {"messages": [response]}

def should_continue(state: State) -> Literal["__end__", "check_query"]:
    messages = state["messages"]
    last_message = messages[-1]
    if not last_message.tool_calls:
        return "__end__"
    else:
        return "check_query"