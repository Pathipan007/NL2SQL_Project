import json
from jinja2 import Template
import ollama

# โหลด Table Metadata Store
try:
    with open("table_metadata.json", "r") as f:
        table_metadata = json.load(f)
except FileNotFoundError:
    print("Error: table_metadata.json not found. Please create the file with table metadata.")
    exit(1)

# ดึง schema ของตาราง
def get_table_schema(table_name):
    if table_name in table_metadata:
        columns = table_metadata[table_name]["columns"]
        schema_str = ", ".join([f"{col} ({dtype})" for col, dtype in columns.items()])
        return schema_str
    return None

# เทมเพลตสำหรับ Text2SQL Prompt
prompt_template = Template("""
เขียนคำสั่ง SQL ใน {{ sql_dialect }} เพื่อตอบคำถาม '{{ question }}' 
โดยใช้ตาราง {{ table }} ที่มีคอลัมน์ {{ schema }}. 
ตอบเฉพาะคำสั่ง SQL ไม่ต้องอธิบาย.
""")

# สร้าง Text2SQL Prompt
def create_text2sql_prompt(question, table, schema, sql_dialect):
    return prompt_template.render(
        question=question,
        table=table,
        schema=schema,
        sql_dialect=sql_dialect
    )

# สร้าง SQL ด้วย Ollama
def generate_sql_with_ollama(prompt):
    try:
        response = ollama.generate(model="gemma3:12B", prompt=prompt)
        return response["response"].strip()
    except Exception as e:
        print(f"Error while generating SQL with Ollama: {e}")
        return None

# รับ Input จากผู้ใช้
def get_user_input():
    question = input("Enter your question (e.g., 'ยอดขายในเดือนนี้คือเท่าไร'): ").strip()
    if not question:
        raise ValueError("Question cannot be empty")
    
    table = input("Enter the table name (e.g., orders): ").strip()
    if not table:
        raise ValueError("Table name cannot be empty")
    
    sql_dialect = input("Enter the SQL dialect (e.g., Presto, MySQL): ").strip()
    if not sql_dialect:
        raise ValueError("SQL dialect cannot be empty")
    
    return {
        "question": question,
        "tables": [table],
        "sql_dialect": sql_dialect
    }

# Main Function
def main():
    print("=== Text-to-SQL System ===")
    try:
        # รับ Input จากผู้ใช้
        user_input = get_user_input()
        print("\nUser Input:", user_input)

        # ดึง schema จาก Table Metadata Store
        schema = get_table_schema(user_input["tables"][0])
        if not schema:
            print(f"Error: Table '{user_input['tables'][0]}' not found in metadata store")
            return

        # สร้าง Text2SQL Prompt
        prompt = create_text2sql_prompt(
            user_input["question"],
            user_input["tables"][0],
            schema,
            user_input["sql_dialect"]
        )
        print("\nGenerated Prompt:", prompt)

        # สร้าง SQL ด้วย Ollama
        generated_sql = generate_sql_with_ollama(prompt)
        if generated_sql:
            print("\nGenerated SQL:", generated_sql)
        else:
            print("Failed to generate SQL.")

    except ValueError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    main()