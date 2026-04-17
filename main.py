import anthropic
import sqlite3
import csv
import json
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic()

# --- Load CSV into SQLite ---
def load_csv_to_db(csv_file):
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    with open(csv_file, "r") as f:
        reader = csv.reader(f)
        headers = next(reader)

        columns = ", ".join([f'"{h.strip()}" TEXT' for h in headers])
        cursor.execute(f"CREATE TABLE data ({columns})")

        placeholders = ", ".join(["?" for _ in headers])
        for row in reader:
            cursor.execute(f"INSERT INTO data VALUES ({placeholders})", row)

    conn.commit()
    print(f"Loaded {csv_file} into database.")

    # Show what was loaded
    cursor.execute("PRAGMA table_info(data)")
    cols = [row[1] for row in cursor.fetchall()]
    cursor.execute("SELECT COUNT(*) FROM data")
    count = cursor.fetchone()[0]
    print(f"  Columns: {', '.join(cols)}")
    print(f"  Rows: {count}\n")

    return conn

db = load_csv_to_db("sales_data.csv")

# --- Define tools ---
tools = [
    {
        "name": "run_sql_query",
        "description": "Runs a SQL query against the dataset and returns results. The table is called 'data'. All columns are TEXT, so cast to REAL or INTEGER for math operations (e.g., CAST(price AS REAL)). If a query fails, read the error message and fix your query.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The SQL query to execute"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "describe_dataset",
        "description": "Returns column names and the first 5 rows of the dataset. Use this first to understand the data before writing queries.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]

# --- Tool functions ---
def run_sql_query(query):
    try:
        cursor = db.cursor()
        cursor.execute(query)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()

        if len(rows) == 0:
            return json.dumps({"columns": columns, "rows": [], "note": "Query returned no results."})

        result = {"columns": columns, "rows": [list(r) for r in rows]}
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "failed_query": query, "hint": "Check column names, table name (it's 'data'), and make sure to CAST text columns to REAL or INTEGER for math."})

def describe_dataset():
    cursor = db.cursor()
    cursor.execute("PRAGMA table_info(data)")
    columns = [{"name": row[1], "type": row[2]} for row in cursor.fetchall()]
    cursor.execute("SELECT * FROM data LIMIT 5")
    sample = [list(r) for r in cursor.fetchall()]
    col_names = [c["name"] for c in columns]
    result = {"columns": columns, "column_names": col_names, "sample_rows": sample, "table_name": "data"}
    return json.dumps(result, indent=2)

tool_functions = {
    "run_sql_query": lambda **kwargs: run_sql_query(kwargs["query"]),
    "describe_dataset": lambda **kwargs: describe_dataset()
}

# --- System prompt ---
SYSTEM_PROMPT = """You are a helpful data analyst agent. When the user asks a question about their data:

1. First use describe_dataset to understand the data structure
2. Then write and run SQL queries to answer the question
3. If a query returns an error, read the error message, fix your query, and try again
4. Present your findings in a clear, concise way
5. When doing math with columns, always CAST them (e.g., CAST(price AS REAL)) since all columns are stored as TEXT

Keep your answers focused and to the point."""

# --- Agent loop ---
MAX_TOOL_CALLS = 10

print("=" * 50)
print("  Data Analysis Agent")
print("=" * 50)
print("Ask questions about your data in plain English.")
print("Type 'quit' to exit.\n")

while True:
    user_input = input("You: ")
    if user_input.lower().strip() in ["quit", "exit", "q"]:
        break

    if not user_input.strip():
        continue

    messages = [
        {"role": "user", "content": user_input}
    ]

    tool_call_count = 0

    # Inner agent loop
    while True:
        if tool_call_count >= MAX_TOOL_CALLS:
            print("\nAgent: I've hit the maximum number of tool calls. Here's what I found so far.")
            break

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if block.type == "text":
                    print(f"\nAgent: {block.text}\n")
            break

        elif response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_call_count += 1
                    func = tool_functions[block.name]
                    result = func(**block.input)

                    # Show what's happening
                    if block.name == "run_sql_query":
                        print(f"  [{tool_call_count}] Running: {block.input['query']}")
                    else:
                        print(f"  [{tool_call_count}] Examining dataset structure...")

                    # Check if there was an error
                    parsed = json.loads(result)
                    if "error" in parsed:
                        print(f"      Error: {parsed['error']} (retrying...)")

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    })

            messages.append({"role": "user", "content": tool_results})
        else:
            print(f"\nUnexpected stop reason: {response.stop_reason}")
            break

db.close()
print("Goodbye!")