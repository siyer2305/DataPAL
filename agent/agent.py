from dotenv import load_dotenv
from langgraph.graph import StateGraph, START
from utils import *

load_dotenv()

builder = StateGraph(State, config_schema=Configuration)

## Adding nodes to the graph
builder.add_node(list_tables)
builder.add_node(call_get_schema)
builder.add_node(get_schema_node, "get_schema")
builder.add_node(generate_query)
builder.add_node(check_query)
builder.add_node(run_query_node, "run_query")

## Adding edges to the graph
builder.add_edge(START, "list_tables")
builder.add_edge("list_tables", "call_get_schema")
builder.add_edge("call_get_schema", "get_schema")
builder.add_edge("get_schema", "generate_query")
builder.add_conditional_edges(
    "generate_query",
    should_continue,
)
builder.add_edge("check_query", "run_query")
builder.add_edge("run_query", "generate_query")

agent = builder.compile()

agent.get_graph().draw_mermaid_png(output_file_path="./assets/agent_graph.png")

if __name__ == "__main__":
    question = "What is the total number of deaths due to rainy conditions?"

    for step in agent.stream(
        {"messages": [{"role": "user", "content": question}]},
        stream_mode="values",
    ):
        step["messages"][-1].pretty_print()
