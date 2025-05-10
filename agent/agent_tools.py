import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st
import os
from io import StringIO
from langchain_core.tools import tool

# Helper to get dataframe, assuming it's stored in streamlit's session state by app.py
# Example: st.session_state['datasets'] = {'my_data.csv': pd.DataFrame(...)}
def _get_dataframe(dataset_name: str) -> pd.DataFrame | None:
    """Safely retrieves a DataFrame from Streamlit's session state."""
    if 'datasets' not in st.session_state:
        st.session_state['datasets'] = {}
    return st.session_state.get('datasets', {}).get(dataset_name)

@tool
def get_data_summary(dataset_name: str) -> str:
    """
    Retrieves a summary of the specified dataset, including column names, data types,
    and the first 5 rows. Use this to understand the data structure before attempting
    more complex operations.
    Input: a dataset_name string.
    Output: A string containing the data summary (column names, dtypes, head).
    """
    df = _get_dataframe(dataset_name)
    if df is None:
        return f"Error: Dataset '{dataset_name}' not found or not loaded. Please ensure the file is uploaded and processed."
    
    buffer = StringIO()
    df.info(buf=buffer)
    info_str = buffer.getvalue()
    
    summary = (
        f"Dataset Summary for '{dataset_name}':\n"
        f"---------------------------------------\n"
        f"Column Information:\n{info_str}\n"
        f"First 5 rows:\n{df.head().to_string()}\n"
        f"---------------------------------------"
    )
    return summary

@tool
def query_data(dataset_name: str, pandas_query_code: str) -> str:
    """
    Executes a snippet of Python code using pandas to query or manipulate the specified dataset.
    The code should be a valid pandas operation on a DataFrame named 'df'.
    The final expression in your pandas_query_code should be what you want to return.
    Example for filtering: 'df[df["column_name"] > 10]'
    Example for descriptive statistics: 'df.describe().to_string()'
    Input:
        dataset_name: The name of the dataset to query.
        pandas_query_code: A string of Python code that performs a pandas operation on a DataFrame named 'df'.
    Output: A string representation of the result (e.g., a DataFrame, Series, or scalar value) or an error message.
    """
    df = _get_dataframe(dataset_name)
    if df is None:
        return f"Error: Dataset '{dataset_name}' not found or not loaded. Please ensure the file is uploaded and processed."
    
    try:
        local_vars = {'df': df.copy(), 'pd': pd}
        # Attempt to evaluate the code as an expression
        result = eval(pandas_query_code, {'pd': pd}, local_vars)

        if isinstance(result, pd.DataFrame):
            return f"Query Result (DataFrame):\n{result.to_string()}"
        elif isinstance(result, pd.Series):
            return f"Query Result (Series):\n{result.to_string()}"
        else:
            return f"Query Result:\n{str(result)}"
            
    except Exception as e:
        # Fallback for statements or more complex code, trying exec
        try:
            exec_globals = {'df': df.copy(), 'pd': pd, '__result__': None}
            exec(f"__result__ = {pandas_query_code}", exec_globals) # Ensure result is captured
            result = exec_globals['__result__']

            if isinstance(result, pd.DataFrame):
                return f"Query Result (DataFrame after exec):\n{result.to_string()}"
            elif isinstance(result, pd.Series):
                return f"Query Result (Series after exec):\n{result.to_string()}"
            else:
                return f"Query Result (after exec):\n{str(result)}"
        except Exception as exec_e:
            return f"Error executing pandas query. Eval error: {str(e)}. Exec error: {str(exec_e)}. Ensure your code uses a DataFrame named 'df' and the last line is an expression or assignable to a result."


@tool
def generate_visualization(dataset_name: str, plot_description: str, python_code_for_plot: str) -> str:
    """
    Generates a visualization based on a Python code snippet (using Matplotlib/Seaborn on a pandas DataFrame 'df')
    and saves it as an image. The code *must* produce a Matplotlib Figure object.
    Ensure the LAST line of your `python_code_for_plot` is an expression that results in the figure object
    (e.g., `df['my_column'].plot(kind='hist').get_figure()` or
    `import matplotlib.pyplot as plt; plt.scatter(df['x'], df['y']); plt.title('My Scatter'); fig=plt.gcf(); fig`).
    Input:
        dataset_name: The name of the dataset to use. The DataFrame will be available as 'df'.
        plot_description: A natural language description of what the plot should represent (used for context).
        python_code_for_plot: A string of Python code that generates a Matplotlib/Seaborn plot.
    Output: A string with the path to the saved visualization image or an error message.
    """
    df = _get_dataframe(dataset_name)
    if df is None:
        return f"Error: Dataset '{dataset_name}' not found or not loaded. Please ensure the file is uploaded and processed."

    viz_dir = "generated_visualizations"
    try:
        if not os.path.exists(viz_dir):
            os.makedirs(viz_dir)
            
        exec_globals = {'df': df.copy(), 'plt': plt, 'pd': pd, 'fig': None}
        
        # Execute the provided Python code for plotting
        # The LLM is responsible for creating code that assigns to 'fig' or results in a figure.
        exec(python_code_for_plot, exec_globals)
        fig = exec_globals.get('fig')

        if fig is None: # If 'fig' wasn't explicitly assigned, try to get current figure
            if plt.get_fignums(): # Check if any figures were created
                 fig = plt.gcf()
            else:
                 return "Error: The provided Python code did not generate a Matplotlib figure or assign it to 'fig'. Please ensure your code creates a plot (e.g., using df.plot() or plt.plot()) and the figure object is the result."

        if not isinstance(fig, plt.Figure):
            return f"Error: The executed code did not result in a Matplotlib Figure object. Got: {type(fig)}. Ensure the final expression in your code yields a figure."

        img_filename = f"visualization_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
        img_path = os.path.join(viz_dir, img_filename)
        
        fig.savefig(img_path)
        plt.close(fig) # Close the figure to free memory

        return f"Visualization generated: '{img_path}'. Description: {plot_description}"
    except Exception as e:
        # Ensure all figures are closed on error too, to prevent leaks if any were created partially
        if 'plt' in locals() and plt.get_fignums():
            plt.close('all')
        return f"Error generating visualization: {str(e)}. Ensure your Python code is correct, uses 'df' DataFrame, and produces a Matplotlib figure. Make sure the figure is assigned to a variable 'fig' or is the last expression."

all_tools = [get_data_summary, query_data, generate_visualization] 