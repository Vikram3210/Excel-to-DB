from flask import Flask, request, render_template, jsonify
import mysql.connector
import pandas as pd
import numpy as np
import os

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Map pandas dtypes to SQL
def map_dtype_to_sql(dtype):
    if np.issubdtype(dtype, np.integer):
        return "INT"
    if np.issubdtype(dtype, np.floating):
        return "FLOAT"
    if np.issubdtype(dtype, np.bool_):
        return "BOOLEAN"
    if np.issubdtype(dtype, np.datetime64):
        return "DATETIME"
    return "VARCHAR(255)"

def row_exists(cursor, table_name, row, columns):
    clause = " AND ".join(f"{col} = %s" for col in columns)
    cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE {clause}", tuple(row[col] for col in columns))
    return cursor.fetchone()[0] > 0

@app.route('/')
def index():
    return render_template('excel.html')

@app.route('/upload', methods=['POST'])
def upload_excel():
    try:
        host = request.form['host']
        user = request.form['user']
        password = request.form['password']
        database = request.form['database']
        table_name = request.form['table_name']
        sheet_name = request.form['sheet_name']
        file = request.files['file']

        if not file:
            return jsonify({"error": "No file uploaded"}), 400

        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(file_path)

        # Connect to MySQL
        db_config = {
            "host": host,
            "user": user,
            "password": password,
            "database": database
        }
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # Read Excel file
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        df.columns = df.columns.str.strip().str.lower()

        # Create table with inferred schema
        columns_sql = ",\n        ".join(f"{col} {map_dtype_to_sql(dtype)}" for col, dtype in df.dtypes.items())
        create_query = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id INT AUTO_INCREMENT PRIMARY KEY,
            {columns_sql}
        )"""
        cursor.execute(create_query)

        # Insert data if row doesn't exist
        columns = df.columns.tolist()
        insert_query = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({', '.join(['%s']*len(columns))})"

        for idx, row in df.iterrows():
            if row.isnull().any():
                return jsonify({"error": f"Missing data at row {idx + 2}"}), 400
            if not row_exists(cursor, table_name, row, columns):
                cursor.execute(insert_query, tuple(row[col] for col in columns))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"message": "Data inserted successfully!"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
