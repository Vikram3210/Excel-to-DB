from flask import Flask, request, render_template, jsonify, redirect, url_for
import mysql.connector
import pandas as pd
import numpy as np
import os

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

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
    return redirect(url_for('upload_page'))

@app.route('/upload_page')
def upload_page():
    message = request.args.get('message')
    error = request.args.get('error')
    return render_template('excel.html', message=message, error=error)

@app.route('/fetch_page')
def fetch_page():
    return render_template('fetch.html')

@app.route("/get_tables")
def get_tables():
    try:
        host = 'localhost'
        user = 'root'
        password = 'root'
        database = 'cdb'

        conn = mysql.connector.connect(
            host=host,
            user=user,
            password=password,
            database=database
        )
        cursor = conn.cursor()
        cursor.execute("SHOW TABLES")
        tables = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()

        return jsonify({"tables": tables})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/upload', methods=['POST'])
def upload_excel():
    try:
        host = 'localhost'
        user = 'root'
        password = 'root'
        database = 'cdb'
        table_name = request.form['table_name']
        sheet_name = request.form['sheet_name']
        file = request.files['file']

        if not file:
            return redirect(url_for('upload_page', error="No file uploaded."))

        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(file_path)

        db_config = {
            "host": host,
            "user": user,
            "password": password,
            "database": database
        }
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        df = pd.read_excel(file_path, sheet_name=sheet_name)
        df.columns = df.columns.str.strip().str.lower()
        excel_columns = df.columns.tolist()

        cursor.execute(f"SHOW TABLES LIKE %s", (table_name,))
        table_exists = cursor.fetchone()

        if table_exists:
            cursor.execute(f"SHOW COLUMNS FROM {table_name}")
            db_columns = [row[0] for row in cursor.fetchall() if row[0] != 'id']
            if set(excel_columns) != set(db_columns):
                return redirect(url_for('upload_page', error="This table is already in use with a different structure. Choose another name for your table."))
        else:
            columns_sql = ",\n     ".join(f"{col} {map_dtype_to_sql(dtype)}" for col, dtype in df.dtypes.items())
            create_query = f"""
            CREATE TABLE {table_name} (
                id INT AUTO_INCREMENT PRIMARY KEY,
                {columns_sql}
            )"""
            cursor.execute(create_query)

        columns = df.columns.tolist()
        insert_query = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({', '.join(['%s']*len(columns))})"
        inserted_rows = []

        for idx, row in df.iterrows():
            if row.isnull().any():
                return redirect(url_for('upload_page', error=f"Missing data at row {idx + 2}"))
            if not row_exists(cursor, table_name, row, columns):
                cursor.execute(insert_query, tuple(row[col] for col in columns))
            inserted_rows.append(row.to_dict())

        conn.commit()
        cursor.close()
        conn.close()

        return redirect(url_for('upload_page', message="Data inserted successfully!"))

    except Exception as e:
        return redirect(url_for('upload_page', error=str(e)))

@app.route('/fetch', methods=['POST'])
def fetch_data():
    try:
        data = request.get_json(force=True)

        host = 'localhost'
        user = 'root'
        password = 'root'
        database = 'cdb'

        table_name = data['table_name']
        column_name = data['column_name']
        search_value = data['description']

        db_config = {
            "host": host,
            "user": user,
            "password": password,
            "database": database
        }

        try:
            conn = mysql.connector.connect(**db_config)
            cursor = conn.cursor()
        except Exception as db_err:
            print("Database connection failed:", db_err)
            return jsonify({"error": "Database connection failed."}), 500

        query = f"SELECT * FROM {table_name} WHERE {column_name} LIKE %s"
        like_pattern = f"%{search_value}%"
        cursor.execute(query, (like_pattern,))
        rows = cursor.fetchall()

        columns = [desc[0] for desc in cursor.description]
        results = [dict(zip(columns, row)) for row in rows]

        cursor.close()
        conn.close()

        return jsonify({"data": results}), 200

    except Exception as e:
        print("Error in /fetch:", str(e))
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True, use_reloader=True)
