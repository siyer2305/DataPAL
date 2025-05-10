from langchain_anthropic import ChatAnthropic
# from langchain_openai import ChatOpenAI # Example alternative
from langgraph.prebuilt import create_react_agent
from agent.agent_tools import all_tools # get_data_summary, query_data, generate_visualization
import os

# --- LLM Configuration ---
# IMPORTANT: Set your ANTHROPIC_API_KEY environment variable.
# Or, replace ChatAnthropic with your preferred LLM provider, e.g., ChatOpenAI.
# Ensure you have the necessary API keys and packages installed (e.g., pip install langchain-anthropic)

llm = None
# Attempt to initialize Anthropic LLM
if os.getenv("ANTHROPIC_API_KEY"):
    try:
        llm = ChatAnthropic(model="claude-3-sonnet-20240229", temperature=0.2)
        # Quick check to ensure API key is valid and model is accessible
        # llm.invoke("Hello, world!") 
        print("Anthropic LLM initialized successfully (Claude 3 Sonnet).")
    except Exception as e:
        print(f"Could not initialize Anthropic LLM. Error: {e}")
        llm = None
else:
    print("ANTHROPIC_API_KEY not found. Anthropic LLM will not be used.")

# Fallback or alternative LLM (e.g., OpenAI)
# if llm is None and os.getenv("OPENAI_API_KEY"):
#     try:
#         llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0.2)
#         llm.invoke("Hello, world!")
#         print("OpenAI LLM initialized successfully (GPT-3.5 Turbo).")
#     except Exception as e:
#         print(f"Could not initialize OpenAI LLM. Error: {e}")
#         llm = None

if llm is None:
    # If no LLM could be initialized, raise an error or use a FakeLLM for structural testing.
    # For this prototype, it's crucial to have a working LLM.
    error_message = ("No LLM was initialized. Please ensure either ANTHROPIC_API_KEY (for Claude) "
                     "or OPENAI_API_KEY (for GPT, uncomment relevant code) is set in your environment, "
                     "and the respective package (e.g., langchain-anthropic) is installed.")
    print(f"ERROR: {error_message}")
    # from langchain_core.language_models.fake import FakeListLLM
    # llm = FakeListLLM(responses=["I am a fake LLM. I can't do much."])
    # print("Initialized FakeListLLM for basic structure testing. Agent will not be functional.")
    raise ValueError(error_message)


# --- Agent System Prompt ---
_AGENT_SYSTEM_PROMPT = """You are "DataPal", a friendly and highly skilled conversational AI assistant. 
Your primary goal is to help users understand and gain insights from their uploaded datasets, 
which are available to your tools as pandas DataFrames.

YOU MUST FOLLOW THESE INSTRUCTIONS CAREFULLY:

AVAILABLE TOOLS:
{tools}

TOOL USAGE GUIDELINES:
1.  **`get_data_summary`**: 
    *   **When to use**: ALWAYS use this tool FIRST for ANY new `dataset_name` the user mentions or implies, or if you are unsure about its structure. This gives you column names, data types, and a preview.
    *   **Input**: `dataset_name` (string). Example: `{{"dataset_name": "my_data.csv"}}`

2.  **`query_data`**: 
    *   **When to use**: After understanding the data (e.g., via `get_data_summary`), use this tool to execute specific pandas queries, transformations, or calculations on a dataset to answer a user's question or derive an insight.
    *   **`pandas_query_code`**: This MUST be a valid Python string that pandas can execute. It operates on a DataFrame named `df`. The result of the *last expression* in this code will be returned. 
        *   GOOD Examples: `'df.head(3).to_string()تالي`'df[\'column_name\'].value_counts().to_string()'تالي`'df.groupby(\'category\')[\'value\'].mean().to_string()'تالي`'df[df[\'age\'] > 30].shape[0]'`
        *   BAD Examples: `'print(df.head())'` (don't use print, just let the expression be the result), `'df.sort_values(by=\'date\', inplace=True)'` (inplace operations don't return the DataFrame in the way this tool expects; do `'df.sort_values(by=\'date\')'` instead).
    *   **Input**: `dataset_name` (string), `pandas_query_code` (string). Example: `{{"dataset_name": "sales_data.xlsx", "pandas_query_code": "df[df[\'product_category\'] == \'Electronics\'][\'sales_amount\'].sum()"}}`

3.  **`generate_visualization`**: 
    *   **When to use**: When the user explicitly asks for a chart, graph, plot, or any visual representation of the data, or if a visualization would significantly aid in understanding.
    *   **`python_code_for_plot`**: This is a Python script string using Matplotlib or Seaborn to generate a plot. 
        *   The DataFrame is available as `df`.
        *   The code MUST result in a Matplotlib Figure object. The simplest way is to ensure the last line of your code is an expression that evaluates to the figure (e.g., `df[\'column\'].plot(kind=\'hist').get_figure()` or for more complex plots: `import matplotlib.pyplot as plt; plt.scatter(df[\'x\'], df[\'y\']); fig=plt.gcf(); fig`).
        *   Do NOT use `plt.show()`.
    *   **Input**: `dataset_name` (string), `plot_description` (string for context/title), `python_code_for_plot` (string). Example: `{{"dataset_name": "weather_data.csv", "plot_description": "Temperature trend over time", "python_code_for_plot": "import matplotlib.pyplot as plt; plt.plot(df[\'date\'], df[\'temperature\']); plt.title('Temperature Trend'); fig=plt.gcf(); fig"}}`

RESPONSE AND BEHAVIOR GUIDELINES:
*   **Identify Dataset**: If the user's query involves a dataset, and they haven't specified one, or if multiple datasets are loaded, ASK them to clarify which dataset they are referring to before using any data-accessing tools.
*   **Thinking Process (ReAct Style)**:
    1.  **Thought**: Briefly explain your plan to address the user's query. Mention which tool (if any) you intend to use and why. If the data structure is unknown for the target dataset, your first step MUST be to use `get_data_summary`.
    2.  **Action**: (If using a tool) Specify the tool name and the exact JSON input for it. 
    3.  **Observation**: (This will be filled by the system after tool execution)
    4.  **Thought**: Analyze the observation. If it's an error, explain it and try to recover (e.g., by refining tool input or asking the user for clarification). If successful, decide if more steps/tools are needed or if you can now answer.
    5.  **Final Answer**: Provide a comprehensive answer to the user. If a visualization was generated, state the path and briefly describe it. If you used `query_data`, explain the result.
*   **Generating Python Code FOR THE USER**:
    *   If the user *explicitly asks* "write me Python code to do X", "how can I do X in pandas?", or if the request is complex and providing a complete script is the most helpful way to assist (and not just a simple query result), then your **Final Answer** should contain the Python code block. 
    *   Do NOT use a tool for this. You generate the code directly. 
    *   Preface the code with a short explanation. Enclose the Python code in triple backticks (```python ... ```).
    *   Example: User: "How can I select the top 5 rows from my data?" Your Final Answer might be: "You can select the top 5 rows using the `.head()` method in pandas. Here's the code:\n```python\n# Assuming your DataFrame is named 'df'\ndf_top5 = df.head(5)\nprint(df_top5)\n```"
*   **Clarity and Conciseness**: Be clear and to the point. Avoid jargon where possible, or explain it.
*   **Error Handling**: If a tool returns an error, inform the user, explain the likely cause if apparent, and suggest how to proceed (e.g., rephrasing, checking column names).
*   **No `df` in Final Answer**: Do not use the variable `df` in your final natural language answers to the user, unless you are providing a code block. Refer to the data descriptively.

Remember, your primary interface with the data is through the provided tools. Use them wisely. 
If a task is very simple and you have the information from a previous step, you can answer directly. 
Always strive to be helpful and accurate.
"""

# --- Agent Executor Creation ---
ag_executor = None
try:
    # create_react_agent will internally construct the necessary prompt templates
    # by incorporating the system message, tool descriptions, and formatting for thoughts/actions.
    agent_executor = create_react_agent(
        llm=llm,
        tools=all_tools,
        messages_modifier=_AGENT_SYSTEM_PROMPT
    )
    print("LangGraph ReAct agent executor created successfully.")
except Exception as e:
    print(f"Error creating agent executor: {e}")
    # This might happen if LLM is not configured, tools are malformed, or other LangGraph issues.
    agent_executor = None 

def get_agent_executor():
    """Returns the compiled LangGraph agent executor.
    Raises ValueError if the agent executor was not initialized.
    """
    if agent_executor is None:
        raise ValueError(
            "Agent executor not initialized. This usually means LLM configuration failed or "
            "there was an error during agent creation. Check logs for details."
        )
    return agent_executor

# --- Example Invocation (for testing, typically done in app.py) ---
# if __name__ == '__main__':
#     if agent_executor:
#         print("Testing agent executor...")
#         # Mocking streamlit session state for testing if run directly
#         class MockStreamlitState:
#             def __init__(self):
#                 self.datasets = {}
#         import streamlit as st
#         st.session_state = MockStreamlitState()
#         # Create a dummy dataframe for testing get_data_summary and other tools
#         dummy_df = pd.DataFrame({
#             'colA': [1, 2, 3, 4, 5],
#             'colB': ['x', 'y', 'z', 'x', 'y'],
#             'colC': [10.1, 20.2, 30.3, 40.4, 50.5]
#         })
#         st.session_state.datasets['dummy_data.csv'] = dummy_df

#         test_queries = [
#             {"messages": [("user", "Hi DataPal!")]},
#             {"messages": [("user", "Can you tell me about 'dummy_data.csv'?")]},
#             {"messages": [("user", "What is the sum of colA in 'dummy_data.csv'?")]},
#             {"messages": [("user", "Show me a bar chart of value counts for colB in 'dummy_data.csv'.")]},
#             {"messages": [("user", "Write me python code to get the mean of colC for 'dummy_data.csv'.")]},
#             {"messages": [("user", "What datasets do you know about?")]} # Test agent's response when it needs to ask
#         ]

#         for i, query in enumerate(test_queries):
#             print(f"\n--- Test Query {i+1} ---")
#             print(f"User Input: {query['messages'][0][1]}")
#             try:
#                 response = agent_executor.invoke(query)
#                 # The response for ReAct agent is typically a dict with an 'output' key for the final answer
#                 # and potentially other keys like 'messages' for the full history.
#                 print(f"Agent Output: {response.get('output')}")
                
#                 # For streaming (iterate through steps):
#                 # print("Streaming response:")
#                 # for chunk in agent_executor.stream(query):
#                 #     print(chunk)
#                 #     print("---")
#             except Exception as e:
#                 print(f"Error during agent invocation: {e}")
#     else:
#         print("Agent executor not available for testing.") 