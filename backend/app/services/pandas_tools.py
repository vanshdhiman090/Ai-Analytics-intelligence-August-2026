import pandas as pd
import logging
from typing import Any

logger = logging.getLogger(__name__)

class QueryTool:
    """A safe structured tool for LLM querying of Pandas DataFrames."""
    
    def __init__(self, df: pd.DataFrame):
        self.df = df

    def query_dataset(
        self, 
        groupby: list[str] | None = None, 
        metrics: dict[str, str] | None = None, 
        filters: list[dict[str, Any]] | None = None,
        sort_by: str | None = None,
        ascending: bool = False,
        limit: int = 10
    ) -> str:
        """
        Query the dataset using Pandas.
        
        Args:
            groupby: List of column names to group by. Can be empty.
            metrics: Dictionary mapping column names to aggregation functions (e.g. {"revenue": "sum", "orders": "count"}).
            filters: List of dictionaries to filter the data. Each dict should have 'column', 'operator' (e.g., '==', '!=', '>', '<', '>=', '<=', 'isin'), and 'value'.
            sort_by: Column to sort the final result by.
            ascending: Whether to sort ascending.
            limit: Number of rows to return.
            
        Returns:
            A string containing the query results in markdown table format, or an error message.
        """
        try:
            temp_df = self.df.copy()
            
            # Apply filters
            if filters:
                for f in filters:
                    col = f.get("column")
                    op = f.get("operator")
                    val = f.get("value")
                    
                    if col not in temp_df.columns:
                        return f"Error: Column {col} not found in dataset. Available columns: {list(temp_df.columns)}"
                        
                    if op == "==":
                        temp_df = temp_df[temp_df[col] == val]
                    elif op == "!=":
                        temp_df = temp_df[temp_df[col] != val]
                    elif op == ">":
                        temp_df = temp_df[temp_df[col] > val]
                    elif op == "<":
                        temp_df = temp_df[temp_df[col] < val]
                    elif op == ">=":
                        temp_df = temp_df[temp_df[col] >= val]
                    elif op == "<=":
                        temp_df = temp_df[temp_df[col] <= val]
                    elif op == "isin":
                        if not isinstance(val, list):
                            return f"Error: 'isin' operator requires a list value, got {type(val)}"
                        temp_df = temp_df[temp_df[col].isin(val)]
                    else:
                        return f"Error: Unsupported operator {op}. Use ==, !=, >, <, >=, <=, or isin."
            
            # If nothing is left
            if temp_df.empty:
                return "Result: 0 rows (No data matched the filters)"
                
            # Aggregate or select
            if groupby and metrics:
                # Group by and aggregate
                missing_groupby = [c for c in groupby if c not in temp_df.columns]
                if missing_groupby:
                    return f"Error: Groupby columns {missing_groupby} not found."
                    
                missing_metrics = [c for c in metrics.keys() if c not in temp_df.columns]
                if missing_metrics:
                    return f"Error: Metric columns {missing_metrics} not found."
                
                res = temp_df.groupby(groupby, dropna=False).agg(metrics).reset_index()
            elif metrics and not groupby:
                # Global aggregation
                missing_metrics = [c for c in metrics.keys() if c not in temp_df.columns]
                if missing_metrics:
                    return f"Error: Metric columns {missing_metrics} not found."
                
                res = temp_df.agg(metrics).to_frame().T
            else:
                # Just return raw rows (useful for inspecting data)
                res = temp_df
                
            # Sort
            if sort_by:
                if sort_by in res.columns:
                    res = res.sort_values(by=sort_by, ascending=ascending)
                else:
                    return f"Error: sort_by column '{sort_by}' not in results. Available: {list(res.columns)}"
            
            # Limit
            if limit:
                res = res.head(limit)
                
            # CSV is built into pandas and avoids the optional `tabulate`
            # dependency required by DataFrame.to_markdown().
            return res.to_csv(index=False)
            
        except Exception as e:
            return f"Query failed with error: {str(e)}"
