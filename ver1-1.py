import ollama
import sqlite3
import os
import re

# ฟังก์ชันดึง Schema
def extract_schema(database_path):
    try:
        conn = sqlite3.connect(database_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()

        schema = {}
        for table in tables:
            table_name = table[0]
            cursor.execute(f"PRAGMA table_info({table_name});")
            columns = cursor.fetchall()
            cursor.execute(f"PRAGMA foreign_key_list({table_name});")
            foreign_keys = cursor.fetchall()
            primary_keys = [col[1] for col in columns if col[5] == 1]
            
            schema[table_name] = {
                'columns': [col[1] for col in columns],
                'data_types': [col[2] for col in columns],
                'primary_keys': primary_keys,
                'foreign_keys': [
                    {'from_column': fk[3], 'to_table': fk[2], 'to_column': fk[4]}
                    for fk in foreign_keys
                ]
            }

        conn.close()
        return schema
    except Exception as e:
        return f"เกิดข้อผิดพลาดในการดึงโครงสร้าง: {e}"

# ฟังก์ชันแปลง Schema เป็นข้อความ
def format_schema_for_prompt(schema):
    schema_text = ""
    for table_name, details in schema.items():
        schema_text += f"- Table: {table_name}\n"
        schema_text += "  Columns:\n"
        for col, data_type in zip(details['columns'], details['data_types']):
            schema_text += f"    • {col} ({data_type})\n"
        schema_text += "  Primary Keys:\n"
        for pk in details['primary_keys']:
            schema_text += f"    • {pk}\n"
        if details['foreign_keys']:
            schema_text += "  Foreign Keys:\n"
            for fk in details['foreign_keys']:
                schema_text += f"    • {fk['from_column']} -> {fk['to_table']}({fk['to_column']})\n"
        schema_text += "\n"
    return schema_text

# ฟังก์ชันรัน SQL query และตรวจสอบผลลัพธ์
def execute_query(query, db_path):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(query)
        result = cursor.fetchall()
        conn.close()
        return result, True, "สำเร็จ"
    except Exception as e:
        return None, False, str(e)

# ฟังก์ชันดึงเฉพาะ SQL query จาก output ของ LLM
def extract_sql_query(response):
    sql_pattern = r"(?i)(SELECT|INSERT|UPDATE|DELETE|WITH|CREATE|ALTER|DROP)\s+.*?(?=;|$|\n\n|\Z)"
    match = re.search(sql_pattern, response, re.DOTALL)
    if match:
        sql_query = match.group(0).strip()
        if not sql_query.endswith(';'):
            sql_query += ';'
        return sql_query
    return None

# ฟังก์ชันสร้าง SQL จากคำถาม NL
def nl2sql(question, schema_text, db_path, examples):
    prompt = f"โครงสร้างฐานข้อมูล:\n{schema_text}\n"
    prompt += "คุณสามารถตอบคำถามได้ทั้งภาษาไทยและภาษาอังกฤษ ซึ่งเป็นภาษาหลักของระบบ\n"
    prompt += "แปลงคำถามภาษาธรรมชาติต่อไปนี้เป็น SQL query:\n"
    prompt += "ให้ตอบเฉพาะ SQL query เท่านั้น ไม่ต้องอธิบายเพิ่มเติมหรือเพิ่มคำอธิบายใดๆ\n"
    prompt += f"คำถาม: \"{question}\"\n\n"

    prompt += "ตัวอย่าง:\n"
    for i, example in enumerate(examples, 1):
        prompt += f"ตัวอย่าง {i}:\nคำถาม: \"{example['question']}\"\nSQL: {example['sql']}\n\n"

    response = ollama.generate(model="gemma3:12b", prompt=prompt)
    raw_output = response['response'].strip()

    sql_query = extract_sql_query(raw_output)
    if not sql_query:
        return None, None, False, "ไม่สามารถดึง SQL query จากคำตอบของ LLM ได้"

    result, success, error = execute_query(sql_query, db_path)
    if not success:
        correction_prompt = f"SQL query ต่อไปนี้มีข้อผิดพลาด: {sql_query}\nข้อผิดพลาด: {error}\n"
        correction_prompt += "กรุณาแก้ไข query และให้ตอบเฉพาะ SQL query เท่านั้น ไม่ต้องอธิบายเพิ่มเติม"
        response = ollama.generate(model="gemma3:12b", prompt=correction_prompt)
        raw_output = response['response'].strip()
        sql_query = extract_sql_query(raw_output)
        if not sql_query:
            return None, None, False, "ไม่สามารถดึง SQL query จากคำตอบแก้ไขของ LLM ได้"
        result, success, error = execute_query(sql_query, db_path)

    return sql_query, result, success, error

# ฟังก์ชันอธิบายผลลัพธ์ให้ผู้ใช้เข้าใจง่าย
def explain_result(question, result, sql_query):
    explanation = "ผลลัพธ์:\n"
    # ตรวจสอบภาษาของคำถาม
    is_thai = any(ord(char) >= 0x0E00 and ord(char) <= 0x0E7F for char in question)

    if "ศิลปิน" in question or "artist" in question.lower():
        explanation += "นี่คือข้อมูลศิลปินที่ตรงกับคำถามของคุณ:\n" if is_thai else "Here is the artist information matching your question:\n"
        for row in result:
            # ดึงข้อมูลศิลปิน, ชื่อเพลง, และความยาว (ถ้ามี)
            artist_name = row[0]
            track_name = row[1] if len(row) > 1 else "ไม่ระบุ"
            duration = row[2] if len(row) > 2 else "ไม่ระบุ"
            if is_thai:
                explanation += f"- ศิลปิน: {artist_name}, เพลง: {track_name}, ความยาว: {duration} มิลลิวินาที\n"
            else:
                explanation += f"- Artist: {artist_name}, Track: {track_name}, Duration: {duration} milliseconds\n"
    elif "หาพนักงาน" in question or "Find all employees" in question:
        explanation += "นี่คือรายชื่อพนักงานที่ตรงกับคำถามของคุณ:\n" if is_thai else "Here are the employees matching your question:\n"
        for row in result:
            explanation += f"- {row[0]} (เงินเดือน: {row[1]})" if "เงินเดือนมากกว่า" in question or "salary greater than" in question else f"- {row[0]}\n"
    elif "นับจำนวน" in question or "Count" in question:
        explanation += "นี่คือจำนวนที่คำนวณได้:\n" if is_thai else "Here is the count result:\n"
        for row in result:
            explanation += f"แผนก {row[0]}: {row[1]} คน\n" if is_thai else f"Department {row[0]}: {row[1]} employees\n"
    else:
        explanation += "นี่คือผลลัพธ์จากการรัน SQL:\n" if is_thai else "Here is the result from running the SQL:\n"
        for row in result:
            explanation += f"{row}\n"
    return explanation

# ตัวอย่าง Few-shot (ปรับให้เหมาะกับ chinook.db และรวมชื่อเพลง ความยาว)
examples = [
    {"question": "List all artists.", "sql": "SELECT Name FROM artists;"},
    {"question": "แสดงรายชื่อศิลปินทั้งหมด", "sql": "SELECT Name FROM artists;"},
    {"question": "นับจำนวนเพลงในแต่ละอัลบั้ม", "sql": "SELECT AlbumId, COUNT(*) FROM tracks GROUP BY AlbumId;"},
    {"question": "Count the number of tracks in each album.", "sql": "SELECT AlbumId, COUNT(*) FROM tracks GROUP BY AlbumId;"},
    {"question": "หาเพลงทั้งหมดจากอัลบั้มที่มี AlbumId เป็น 1", "sql": "SELECT Name FROM tracks WHERE AlbumId = 1;"},
    {"question": "Find all tracks from the album with AlbumId 1.", "sql": "SELECT Name FROM tracks WHERE AlbumId = 1;"},
    {"question": "หาศิลปินที่มีเพลงยาวที่สุด", "sql": "SELECT A.Name, T.Name, T.Milliseconds FROM artists A JOIN albums AL ON A.ArtistId = AL.ArtistId JOIN tracks T ON AL.AlbumId = T.AlbumId ORDER BY T.Milliseconds DESC LIMIT 1;"},
    {"question": "Find the artist with the longest track.", "sql": "SELECT A.Name, T.Name, T.Milliseconds FROM artists A JOIN albums AL ON A.ArtistId = AL.ArtistId JOIN tracks T ON AL.AlbumId = T.AlbumId ORDER BY T.Milliseconds DESC LIMIT 1;"}
]

def main():
    print("ยินดีต้อนรับสู่ NL2SQL Helper!")
    print("เครื่องมือนี้ช่วยคุณสร้าง SQL จากคำถามภาษาธรรมชาติ")
    print("รองรับคำถามทั้งภาษาไทยและภาษาอังกฤษเป็นภาษาหลัก")
    print("คุณไม่ต้องรู้เรื่อง SQL หรือโครงสร้างฐานข้อมูล ระบบจัดการให้อัตโนมัติ")

    print("\nกรุณาระบุไฟล์ฐานข้อมูล (เช่น chinook.db):")
    print("ถ้าไม่มีไฟล์ ให้สร้างไฟล์ก่อน")
    db_path = input("พิมพ์ชื่อไฟล์ฐานข้อมูล: ").strip()

    if not os.path.exists(db_path):
        print(f"ไม่พบไฟล์ {db_path} กรุณาสร้างไฟล์ฐานข้อมูลก่อน")
        return

    schema = extract_schema(db_path)
    schema_text = format_schema_for_prompt(schema)

    print("\nนี่คือโครงสร้างของฐานข้อมูลที่เลือก:")
    print(schema_text)

    while True:
        print("\nพิมพ์คำถามของคุณ (เช่น หาศิลปินที่มีเพลงยาวที่สุด หรือ Find the artist with the longest track)")
        print("พิมพ์ 'ออก' เพื่อออกจากโปรแกรม")
        question = input("คำถาม: ").strip()

        if question.lower() == 'ออก':
            print("ออกจากโปรแกรม")
            break

        if not question:
            print("กรุณาใส่คำถาม")
            continue

        print("\nกำลังสร้าง SQL...")
        sql_query, result, success, error = nl2sql(question, schema_text, db_path, examples)

        if not success:
            print("\nข้อผิดพลาด:")
            print(error)
            continue

        print("\nSQL ที่สร้างให้คุณ:")
        print(sql_query)

        print("\n" + explain_result(question, result, sql_query))

if __name__ == "__main__":
    main()