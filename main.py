import anthropic
import sqlite3
import csv
import json
import os
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic()

# --- Load data into SQLite based on file type ---
def load_file_to_db(filepath):
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".csv":
        with open(filepath, "r") as f:
            reader = csv.reader(f)
            headers = [h.strip() for h in next(reader)]
            columns = ", ".join([f'"{h}" TEXT' for h in headers])
            cursor.execute(f"CREATE TABLE data ({columns})")
            placeholders = ", ".join(["?" for _ in headers])
            for row in reader:
                cursor.execute(f"INSERT INTO data VALUES ({placeholders})", row)

    elif ext == ".tsv":
        with open(filepath, "r") as f:
            reader = csv.reader(f, delimiter="\t")
            headers = [h.strip() for h in next(reader)]
            columns = ", ".join([f'"{h}" TEXT' for h in headers])
            cursor.execute(f"CREATE TABLE data ({columns})")
            placeholders = ", ".join(["?" for _ in headers])
            for row in reader:
                cursor.execute(f"INSERT INTO data VALUES ({placeholders})", row)

    elif ext in [".xlsx", ".xls"]:
        import openpyxl
        wb = openpyxl.load_workbook(filepath, read_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        headers = [str(h).strip() for h in rows[0]]
        columns = ", ".join([f'"{h}" TEXT' for h in headers])
        cursor.execute(f"CREATE TABLE data ({columns})")
        placeholders = ", ".join(["?" for _ in headers])
        for row in rows[1:]:
            values = [str(v) if v is not None else "" for v in row]
            cursor.execute(f"INSERT INTO data VALUES ({placeholders})", values)
        wb.close()

    elif ext in [".db", ".sqlite", ".sqlite3"]:
        # Connect to the existing database file
        source = sqlite3.connect(filepath)
        # Get all table names
        tables = source.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if not tables:
            print("No tables found in database file.")
            source.close()
            return None

        # Copy all tables into our in-memory database
        for (table_name,) in tables:
            create_sql = source.execute(f"SELECT sql FROM sqlite_master WHERE name='{table_name}'").fetchone()[0]
            cursor.execute(create_sql)
            rows = source.execute(f"SELECT * FROM \"{table_name}\"").fetchall()
            if rows:
                placeholders = ", ".join(["?" for _ in rows[0]])
                cursor.executemany(f"INSERT INTO \"{table_name}\" VALUES ({placeholders})", rows)

        source.close()

        # Show all available tables
        print(f"  Tables found: {', '.join(t[0] for t in tables)}")
        conn.commit()

        # Show info for each table
        for (table_name,) in tables:
            cursor.execute(f'PRAGMA table_info("{table_name}")')
            cols = [row[1] for row in cursor.fetchall()]
            cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
            count = cursor.fetchone()[0]
            print(f"  Table '{table_name}': {', '.join(cols)} ({count} rows)")

        print()
        return conn

    else:
        print(f"Unsupported file type: {ext}")
        return None

    conn.commit()

    # Show what was loaded
    cursor.execute("PRAGMA table_info(data)")
    cols = [row[1] for row in cursor.fetchall()]
    cursor.execute("SELECT COUNT(*) FROM data")
    count = cursor.fetchone()[0]
    print(f"Loaded {filepath}")
    print(f"  Columns: {', '.join(cols)}")
    print(f"  Rows: {count}\n")

    return conn

# --- Get the file path ---
print("=" * 50)
print("  Data Analysis Agent")
print("=" * 50)
print("Supported files: .csv, .tsv, .xlsx, .db, .sqlite")
print()

filepath = input("Enter the path to your data file: ").strip().strip('"')

if not os.path.exists(filepath):
    print(f"File not found: {filepath}")
    exit()

db = load_file_to_db(filepath)
if db is None:
    exit()

# --- Define tools ---
tools = [
    {
        "name": "run_sql_query",
        "description": "Runs a SQL query against the dataset and returns results. For CSV/TSV/XLSX files, the table is called 'data'. For .db files, there may be multiple tables — use list_tables first. All columns from CSV/TSV/XLSX are TEXT, so cast to REAL or INTEGER for math. If a query fails, read the error and fix it.",
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
        "description": "Returns all table names, their columns, and sample rows. Use this first to understand the data before writing queries.",
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
        return json.dumps({"error": str(e), "failed_query": query, "hint": "Check column names, table names, and make sure to CAST text columns to REAL or INTEGER for math."})

def describe_dataset():
    cursor = db.cursor()
    tables = cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    result = {"tables": []}

    for (table_name,) in tables:
        cursor.execute(f'PRAGMA table_info("{table_name}")')
        columns = [{"name": row[1], "type": row[2]} for row in cursor.fetchall()]
        cursor.execute(f'SELECT * FROM "{table_name}" LIMIT 5')
        sample = [list(r) for r in cursor.fetchall()]
        col_names = [c["name"] for c in columns]
        result["tables"].append({
            "table_name": table_name,
            "columns": columns,
            "column_names": col_names,
            "sample_rows": sample
        })

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
5. When doing math with columns, always CAST them (e.g., CAST(price AS REAL)) since columns from CSV/TSV/XLSX files are stored as TEXT
6. For database files, there may be multiple tables — check all available tables

Keep your answers focused and to the point. Do NOT ask follow-up questions. Just answer the question and stop."""

# --- Agent loop ---
MAX_TOOL_CALLS = 10

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

                    if block.name == "run_sql_query":
                        print(f"  [{tool_call_count}] Running: {block.input['query']}")
                    else:
                        print(f"  [{tool_call_count}] Examining dataset structure...")

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