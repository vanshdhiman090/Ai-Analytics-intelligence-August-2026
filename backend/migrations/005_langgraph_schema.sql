-- Isolate LangGraph's internal tables from the application's human checkpoints table.
CREATE SCHEMA IF NOT EXISTS langgraph_checkpoints;
