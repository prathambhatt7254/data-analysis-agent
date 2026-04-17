# Data Analysis Agent

An AI-powered data analysis agent that lets you ask questions about any CSV dataset in plain English. The agent uses Claude's API to automatically write and execute SQL queries, handle errors, and present results — no SQL knowledge required.

## How It Works

1. You provide a CSV file
2. The agent loads it into an in-memory SQLite database
3. You ask questions in plain English
4. The agent figures out what SQL to run, executes it, and gives you the answer

Under the hood, this is an LLM agent loop: Claude receives your question, decides which tool to call (examine the dataset structure or run a SQL query), observes the result, and repeats until it has a final answer. If a query fails, the agent reads the error and retries with a corrected query.

## Example

```
You: What product generated the most revenue?
  [1] Examining dataset structure...
  [2] Running: SELECT product, category, CAST(price AS REAL) * CAST(quantity AS INTEGER) AS revenue FROM data ORDER BY revenue DESC LIMIT 1

Agent: The product that generated the most revenue is the **Laptop** in the Electronics category, with a total revenue of $4,999.95 (priced at $999.99 with 5 units sold).
```

## Setup

1. Clone the repo:
   ```
   git clone https://github.com/prathambhatt7254/data-analysis-agent.git
   cd data-analysis-agent
   ```

2. Create and activate a virtual environment:
   ```
   python -m venv venv
   venv\Scripts\activate        # Windows
   source venv/bin/activate     # Mac/Linux
   ```

3. Install dependencies:
   ```
   pip install anthropic python-dotenv
   ```

4. Create a `.env` file and add your Anthropic API key:
   ```
   ANTHROPIC_API_KEY=your-api-key-here
   ```

5. Run the agent:
   ```
   python main.py
   ```

## Tools

The agent has access to two tools:

- **describe_dataset** — Returns column names, types, and sample rows so the agent can understand the data before querying it
- **run_sql_query** — Executes a SQL query against the dataset and returns results. Includes error handling so the agent can fix and retry failed queries

## Tech Stack

- Python
- Anthropic Claude API (Sonnet 4.6)
- SQLite (in-memory)
- Tool use / function calling

## Using Your Own Data

Replace `sales_data.csv` with any CSV file and run the agent. It automatically detects columns and loads the data. No code changes needed.
