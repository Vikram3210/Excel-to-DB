from flask import Flask,session, send_file , request, render_template, jsonify, redirect, url_for
import mysql.connector
import pymysql
#from datetime import datetime
import pandas as pd
import logging
from rapidfuzz import fuzz
import numpy as np
import os 

app = Flask(__name__)
#3rd module
app.secret_key = "super_secret_123"
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
#3rd module
# Get the path to your Desktop
DOWNLOAD_FOLDER = os.path.join(os.path.expanduser("~"), "Desktop", "Downloads")  # Update the path to Desktop

@app.route('/compare_page')
def compare_page():
    return render_template('compare.html')
#till here
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
    
@app.route('/get_sheet_names', methods=['POST'])
def get_sheet_names():
    try:
        file = request.files['file']
        if not file:
            return jsonify({"error": "No file provided"}), 400

        xls = pd.ExcelFile(file)
        return jsonify({"sheets": xls.sheet_names})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/upload', methods=['POST'])
def upload_excel():
    try:
        host = 'localhost'
        user = 'root'
        password = 'root'
        database = 'cdb'
        table_name = request.form['table_name'].strip()
        sheet_name = request.form['sheet_name'].lower().strip()
        filename = request.form['file_name']  # Use previously saved file
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        # file = request.files['file']

        if not os.path.exists(file_path):
            return redirect(url_for('upload_page', error="Uploaded file not found on server."))
        #if not file:
        #     return redirect(url_for('upload_page', error="No file uploaded."))

        # # Save the file
        # file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        # file.save(file_path)

        # Database connection configuration
        db_config = {
            "host": host,
            "user": user,
            "password": password,
            "database": database
        }
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # Load Excel file and handle sheet name selection
        try:
            xls = pd.ExcelFile(file_path)
            available_sheets = xls.sheet_names
        except Exception as e:
            return redirect(url_for('upload_page', error=f"Error loading sheet names: {str(e)}"))
        
        if sheet_name == "all":
            xls = pd.ExcelFile(file_path)
            df_list = []
            for sheet in xls.sheet_names:
                if sheet.lower() != "information":  # Skip the "infromation" sheet
                    temp_df = pd.read_excel(xls, sheet_name=sheet).iloc[:, 1:5]
                    temp_df.columns = temp_df.columns.str.strip().str.lower().str.replace(' ', '_')
                    df_list.append(temp_df)
            df = pd.concat(df_list, ignore_index=True)

            # CLEANING STARTS HERE
            df = df.loc[:, df.columns.notna()]
            df = df.loc[:, df.columns != '']
            df.columns = df.columns.str.strip().str.lower().str.replace(' ', '_')
            df = df.dropna(how='all')
            df.reset_index(drop=True, inplace=True)
            df = df.where(pd.notna(df), None)


        else:
            df = pd.read_excel(file_path, sheet_name=sheet_name).iloc[:, 1:5]
            df = df.loc[:, df.columns.notna()]
            df = df.loc[:, df.columns != '']
            df.columns = df.columns.str.strip().str.lower().str.replace(' ', '_')
            df = df.dropna(how='all')
            df.reset_index(drop=True, inplace=True)
            df = df.where(pd.notna(df), None)
            df.columns = df.columns.str.strip().str.lower().str.replace(' ', '_')

        excel_columns = df.columns.tolist()


        # Check for missing values before proceeding
        for idx, row in df.iterrows():
            if pd.isnull(row[df.columns[1]]):
                print(df)
                return redirect(url_for('upload_page', error=f"Missing or invalid data at row {idx}"))
                

        # Check if table already exists
        cursor.execute(f"SHOW TABLES LIKE %s", (table_name,))
        table_exists = cursor.fetchone()

        if table_exists:
            cursor.execute(f"SHOW COLUMNS FROM {table_name}")
            db_columns = [row[0] for row in cursor.fetchall()]
            # Ensure the columns match between the Excel and DB (excluding the primary key column)
            if set(excel_columns) != set(db_columns):
                return redirect(url_for('upload_page', error="This table is already in use with a different structure. Choose another name for your table."))
        else:
            # Create table if it doesn't exist
            columns_sql = ",\n     ".join(f"{col} {map_dtype_to_sql(dtype)}" for col, dtype in df.dtypes.items())
            if len(excel_columns) >= 2:
                second_col = excel_columns[1]
                columns_sql = columns_sql.replace(
                    f"{second_col} {map_dtype_to_sql(df[second_col].dtype)}",
                    f"{second_col} {map_dtype_to_sql(df[second_col].dtype)} PRIMARY KEY"
                )
            create_query = f"CREATE TABLE {table_name} (\n    {columns_sql}\n)"
            cursor.execute(create_query)

        # Insert or Update data
        insert_query = f"INSERT INTO {table_name} ({', '.join(excel_columns)}) VALUES ({', '.join(['%s']*len(excel_columns))})"
        primary_key_col = excel_columns[1]  # Assuming the first column is the primary key (this should be dynamically handled in your case)
        inserted_rows = 0
        updated_rows = 0

        for idx, row in df.iterrows():
            cursor.execute(
                f"SELECT {', '.join(excel_columns)} FROM {table_name} WHERE {primary_key_col} = %s",
                (row[primary_key_col],)
            )
            existing = cursor.fetchone()

            if existing:
                existing_dict = dict(zip(excel_columns, existing))

                # Normalize function for comparing values
                def normalize(val):
                    if val is None:
                        return ''
                    elif isinstance(val, (int, float)):
                        return str(val).strip()
                    return str(val).strip().lower()

                needs_update = False
                # Compare non-primary key columns
                for col in excel_columns:
                    if col == primary_key_col:
                        continue

                    excel_val = normalize(row[col])
                    db_val = normalize(existing_dict[col])

                    print(f"Comparing column '{col}': Excel='{excel_val}' | DB='{db_val}'")
                    
                    if excel_val != db_val:
                        print(f"-> Change detected in '{col}'")
                        needs_update = True
                        break

                if needs_update:
                    update_cols = [f"{col} = %s" for col in excel_columns if col != primary_key_col]
                    update_query = f"""
                        UPDATE {table_name}
                        SET {', '.join(update_cols)}
                        WHERE {primary_key_col} = %s
                    """
                    update_values = [row[col] for col in excel_columns if col != primary_key_col]
                    update_values.append(row[primary_key_col])
                    cursor.execute(update_query, update_values)
                    updated_rows += 1
            else:
                # Insert new row
                cursor.execute(insert_query, tuple(row[col] for col in excel_columns))
                inserted_rows += 1

        conn.commit()
        cursor.close()
        conn.close()

        # Final message
        if inserted_rows == 0 and updated_rows == 0:
            message = "All rows already exist. No updates or new data inserted."
        elif inserted_rows == 0:
            message = f"No new rows inserted, but {updated_rows} row(s) updated successfully."
        elif updated_rows == 0:
            message = f"{inserted_rows} new row(s) inserted. No rows were updated."
        else:
            message = f"{inserted_rows} new row(s) inserted and {updated_rows} row(s) updated successfully."

        return redirect(url_for('upload_page', message=message))

    except Exception as e:
        return redirect(url_for('upload_page', error=f"Error: {str(e)}"))

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
        search_value = data['search_value']

        if not table_name or not search_value:
            return jsonify({"error": "Table name or search value missing."}), 400

        # column_name = 'cdb_pid_no'  # Ensure this is the correct column name

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

        # Check if the column exists in the table
        cursor.execute(f"SHOW COLUMNS FROM {table_name}")
        column_names = [row[0].lower() for row in cursor.fetchall()]
        if column_name.lower() not in column_names:
            return jsonify({"error": f"'{column_name}' column not found in '{table_name}'."}), 400
        

        # Perform the LIKE search
        # Get columns in original Excel order from INFORMATION_SCHEMA (excluding 'id')
        cursor.execute("""
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME != 'id'
            ORDER BY ORDINAL_POSITION
        """, (database, table_name))
        excel_columns = [row[0] for row in cursor.fetchall()]

        if len(excel_columns) < 2:
            return jsonify({"error": "Not enough columns to treat third one as primary key."}), 400

        # Move the third column to front
        # primary_key_col = excel_columns[1]
        # if primary_key_col == None:
        #     return jsonify({"error primary key missing": str(e)}),
        # remaining_cols = [col for i, col in enumerate(excel_columns) if i != 1]
        # ordered_columns = [primary_key_col] + remaining_cols


        # Use LIKE search
        like_pattern = f"%{search_value}%"
        query = f"SELECT * FROM {table_name} WHERE {column_name} LIKE %s"
        cursor.execute(query, (like_pattern,))
        rows = cursor.fetchall()

#        columns = ordered_columns


        columns = [desc[0] for desc in cursor.description]
        results = [dict(zip(columns, row)) for row in rows]

        cursor.close()
        conn.close()

        return jsonify({"data": results}), 200

    except Exception as e:
        print("Error in /fetch:", str(e))
        return jsonify({"error": str(e)}), 500


# Set up logging
logging.basicConfig(level=logging.DEBUG)
#FUZZY_THRESHOLD = 80

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# @app.route("/compare_excel", methods=["POST"])
# def compare_excel():
#     try:
#         file = request.files.get("excel_file")
#         table_name = request.form.get("table_name")

#         if not file or not table_name:
#             return jsonify({"error": "Missing file or table name."}), 400

#         # Read and normalize Excel columns
#         df_input = pd.read_excel(file)
#         df_input.columns = [str(col).strip().lower().replace(" ", "_") for col in df_input.columns]

#         if 'description' not in df_input.columns or 'a' not in df_input.columns or 'b' not in df_input.columns:
#             return jsonify({"error": "Excel file must have 'description', 'a', and 'b' columns."}), 400

#         merged_rows = []

#         db_config = {
#             'host': 'localhost',
#             'user': 'root',
#             'password': 'root',
#             'database': 'cdb'
#         }

#         try:
#             conn = mysql.connector.connect(**db_config)
#             cursor = conn.cursor()
#         except Exception as db_err:
#             print("Database connection failed:", db_err)
#             return jsonify({"error": "Database connection failed."}), 500
        
#         db_df = pd.read_sql(f"SELECT * FROM {table_name}", conn)
#         db_df['description'] = db_df['description'].astype(str).str.strip().str.lower()
#         conn.close()

#         for _, row in df_input.iterrows():
#             input_desc = str(row['description']).strip().lower()

#             best_match = None
#             best_score = 0

#             for _, db_row in db_df.iterrows():
#                 db_desc = db_row['description']
#                 score = fuzz.token_sort_ratio(input_desc, db_desc)
#                 if score > best_score:
#                     best_score = score
#                     best_match = db_row

#             if best_score >= FUZZY_THRESHOLD and best_match is not None:
#                 matched_row = best_match.to_dict()

#                 # Combine all columns from the input row
#                 input_row_dict = row.to_dict()

#                 # Normalize the description (input side only)
#                 input_row_dict['description'] = input_desc

#                 # Update matched row with all input columns
#                 matched_row.update(input_row_dict)

#                 print(f"Match found: Description: {input_desc}, Match Score: {best_score}")
#                 merged_rows.append(matched_row)

#             #Assuming best_match is the row from DB with the best fuzzy match



#         if not merged_rows:
#             return jsonify({"error": "No matches found in the database."}), 200

#         merged_df = pd.DataFrame(merged_rows)
#         output_path = os.path.join(UPLOAD_FOLDER, "merged_output.xlsx")
#         merged_df.to_excel(output_path, index=False)

#         return jsonify({
#             "message": "Comparison successful.",
#             "filename": "merged_output.xlsx",
#             "merged_data": merged_df.fillna("").to_dict(orient="records")
#         })

@app.route("/compare_excel", methods=["POST"])
def compare_excel():
    try:
        file = request.files.get("excel_file")
        table_name = request.form.get("table_name")

        if not file or not table_name:
            return jsonify({"error": "Missing file or table name."}), 400

        df_input = pd.read_excel(file)
        df_input.columns = [str(col).strip().lower().replace(" ", "_") for col in df_input.columns]

        if 'description' not in df_input.columns:
            return jsonify({"error": "Excel file must have 'description' column."}), 400

        merged_rows = []

        db_config = {
            'host': 'localhost',
            'user': 'root',
            'password': 'root',
            'database': 'cdb'
        }

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        for _, row in df_input.iterrows():
            input_desc = str(row['description']).strip()

            query = f"""
                SELECT *, MATCH(description) AGAINST (%s) AS match_score
                FROM {table_name}
                WHERE MATCH(description) AGAINST (%s)
                ORDER BY match_score DESC
                LIMIT 1
            """
            cursor.execute(query, (input_desc, input_desc))
            best_match = cursor.fetchone()

            if best_match:
                input_row_dict = row.to_dict()
                input_row_dict['description'] = input_desc
                best_match.update(input_row_dict)
                merged_rows.append(best_match)
                print(f"✔ Matched: {input_desc} → {best_match['description']} (Score: {best_match['match_score']})")
            else:
                print(f"✖ No match for: {input_desc}")

        cursor.close()
        conn.close()

        if not merged_rows:
            return jsonify({"error": "No matches found."}), 200

        merged_df = pd.DataFrame(merged_rows)
        output_path = os.path.join(UPLOAD_FOLDER, "merged_output.xlsx")
        merged_df.to_excel(output_path, index=False)

        return jsonify({
            "message": "Comparison successful.",
            "filename": "merged_output.xlsx",
            "merged_data": merged_df.fillna("").to_dict(orient="records")
        })

    except Exception as e:
        print("Error:", e)
        return jsonify({"error": "Comparison failed."}), 500


@app.route("/download_excel")
def download_excel():
    filename = request.args.get("filename")
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    else:
        return "File not found", 404

    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True, use_reloader=True)
