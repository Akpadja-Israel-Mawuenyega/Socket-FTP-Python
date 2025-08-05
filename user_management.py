import pymysql.cursors
import logging
import bcrypt
from pymysql.err import IntegrityError
import threading
import sys
import os
import configparser
from pymysqlpool import ConnectionPool

class DatabaseManager:
    def __init__(self, db_config_parser):
        self.db_config = {
            'host': db_config_parser['DB_HOST'],
            'user': db_config_parser['DB_USER'],
            'password': os.getenv('DB_PASSWORD', db_config_parser['DB_PASSWORD']),
            'db': db_config_parser['DB_NAME'],
            'cursorclass': pymysql.cursors.DictCursor,
        }
        self.db_pool = None
        
        try:
            self.db_pool = ConnectionPool(
                autocommit=True,
                charset='utf8mb4',
                maxsize=10,
                **self.db_config
            )
            logging.info("Database connection pool initialized.")
        except Exception as e:
            logging.critical(f"Error initializing MySQL connection pool: {e}", exc_info=True)
            sys.exit(1)
            
    def create_user_table_if_not_exists(self):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    create_table_sql = """
                    CREATE TABLE IF NOT EXISTS users (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        username VARCHAR(255) NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        role VARCHAR(50) DEFAULT 'user',
                        session_id VARCHAR(36) NULL
                    )
                    """
                    cursor.execute(create_table_sql)
                    logging.info("User database table ensured in 'ftp_users'.")
                except Exception as e:
                    logging.critical(f"Error creating user table: {e}", exc_info=True)

    def register_user(self, username, password, role='user'):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
                    cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)", (username, password_hash, role))
                    return True
                except IntegrityError:
                    logging.warning(f"Registration failed: Username '{username}' already exists.")
                    return False
                except pymysql.Error as e:
                    logging.error(f"Error registering user '{username}': {e}", exc_info=True)
                    return False             
    
    def get_user_by_username(self, username):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute("SELECT id, username, password_hash, role, session_id FROM users WHERE username = %s", (username,))
                    result = cursor.fetchone()
                    return result
                except pymysql.Error as e:
                    logging.error(f"Error getting user by username '{username}': {e}", exc_info=True)
                    return None
   
    def get_user_by_id(self, user_id):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute("SELECT id, username, password_hash, role, session_id FROM users WHERE id = %s", (user_id,))
                    result = cursor.fetchone()
                    return result
                except pymysql.Error as e:
                    logging.error(f"Error getting user by ID '{user_id}': {e}", exc_info=True)
                    return None             
    
    def get_user_id_by_username(self, username):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
                    result = cursor.fetchone()
                    return result['id'] if result else None
                except pymysql.Error as e:
                    logging.error(f"Error getting user ID for '{username}': {e}", exc_info=True)
                    return None
    
    def update_user_session(self, user_id, session_id):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute("UPDATE users SET session_id = %s WHERE id = %s", (session_id, user_id))
                except pymysql.Error as e:
                    logging.error(f"Error updating session for user ID '{user_id}': {e}", exc_info=True)

    def update_user_session_by_username(self, username, session_id):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute("UPDATE users SET session_id = %s WHERE username = %s", (session_id, username))
                except pymysql.Error as e:
                    logging.error(f"Error updating session for user '{username}': {e}", exc_info=True)
    
    def create_files_table_if_not_exists(self):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    create_table_sql = """
                    CREATE TABLE IF NOT EXISTS files (
                        file_id INT AUTO_INCREMENT PRIMARY KEY,
                        owner_id INT NOT NULL,
                        file_name VARCHAR(255) NOT NULL,
                        file_size BIGINT NOT NULL,
                        is_public BOOLEAN NOT NULL DEFAULT FALSE,
                        recipient_id INTEGER DEFAULT NULL,
                        upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (recipient_id) REFERENCES users(id),
                        FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
                    )
                    """
                    cursor.execute(create_table_sql)
                    logging.info("Files table checked/created successfully.")
                except Exception as e:
                    logging.error(f"Error creating files table: {e}", exc_info=True)
    
    def add_file_record(self, owner_id, file_name, file_size, is_public, recipient_id=None):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute(
                        "INSERT INTO files (owner_id, file_name, file_size, is_public, recipient_id) VALUES (%s, %s, %s, %s, %s)",
                        (owner_id, file_name, file_size, is_public, recipient_id)
                    )
                    logging.info(f"File record for '{file_name}' added to database.")
                    return True
                except Exception as e:
                    logging.error(f"Failed to add file record: {e}")
                    return False
    
    def get_files(self, owner_id=None, is_public=None):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    query = "SELECT file_id, file_name, file_size, owner_id FROM files WHERE 1=1"
                    params = []
                    if owner_id is not None:
                        query += " AND owner_id = %s"
                        params.append(owner_id)
                    if is_public is not None:
                        query += " AND is_public = %s"
                        params.append(is_public)
                    cursor.execute(query, tuple(params))
                    return cursor.fetchall()
                except Exception as e:
                    logging.error(f"Failed to get file list: {e}")
                    return []
    
    def get_public_file_record(self, file_name):
        with self.db_pool.get_connection() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                try:
                    cursor.execute("""
                        SELECT * FROM files
                        WHERE file_name = %s AND is_public = TRUE AND recipient_id IS NULL;
                    """, (file_name,))
                    return cursor.fetchone()
                except pymysql.Error as e:
                    logging.error(f"Database error while fetching public file record: {e}")
                    return None  
    
    def get_file_record_by_id(self, file_id):
        with self.db_pool.get_connection() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                try:
                    cursor.execute("""
                        SELECT * FROM files
                        WHERE file_id = %s;
                    """, (file_id,))
                    return cursor.fetchone()
                except pymysql.Error as e:
                    logging.error(f"Database error while fetching file record by ID: {e}")
                    return None                      
    
    def get_private_file_record(self, file_name, owner_id):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute("""
                        SELECT * FROM files 
                        WHERE file_name = %s AND owner_id = %s AND is_public = FALSE AND recipient_id IS NULL;
                    """, (file_name, owner_id))
                    file_record = cursor.fetchone()
                    logging.info(f"DEBUG: get_private_file_record query result: {file_record}")
                    return file_record
                except pymysql.Error as e:
                    logging.error(f"Database error: {e}")
                    return None
    
    def get_file_record_in_shared_folder(self, file_name, recipient_id):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:      
                    cursor.execute("""
                        SELECT * FROM files
                        WHERE file_name = %s AND recipient_id = %s AND is_public = FALSE;
                    """, (file_name, recipient_id))
                    return cursor.fetchone()
                except pymysql.Error as e:
                    logging.error(f"Database error while fetching shared file record: {e}")
                    return None
                  
    def get_files_by_owner(self, owner_id):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute("SELECT file_name FROM files WHERE owner_id = %s AND is_public = FALSE", (owner_id,))
                    return cursor.fetchall()
                except Exception as e:
                    logging.error(f"Failed to get files for owner {owner_id}: {e}")
                    return []

    def get_public_files(self):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute("SELECT file_id, file_name FROM files WHERE is_public = TRUE")
                    return cursor.fetchall()
                except Exception as e:
                    logging.error(f"Failed to get public files: {e}")
                    return []
    
    def update_file_visibility(self, file_id, new_is_public):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute(
                        "UPDATE files SET is_public = %s WHERE file_id = %s",
                        (new_is_public, file_id)
                    )
                    return cursor.rowcount > 0
                except Exception as e:
                    logging.error(f"Error updating file visibility: {e}", exc_info=True)
                    return False
    
    def delete_file(self, file_id, user_id, user_role):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    file_record = self.get_file_record_by_id(file_id=file_id)
                    if not file_record:
                        logging.warning(f"File ID {file_id} not found.")
                        return None, None, None

                    file_name = file_record['file_name']
                    owner_id = file_record['owner_id']

                    if user_role == 'admin':
                        if not file_record['is_public']:
                            logging.warning(f"Admin attempted to delete a non-public file with ID {file_id}.")
                            return None, None, None

                        cursor.execute("DELETE FROM files WHERE file_id = %s", (file_id,))
                        if cursor.rowcount == 1:
                            logging.info(f"Public file record (ID: {file_id}) deleted by an admin.")
                            return file_name, owner_id, file_record['is_public']
                        else:
                            return None, None, None
                    else:
                        cursor.execute(
                            "DELETE FROM files WHERE file_id = %s AND owner_id = %s",
                            (file_id, user_id)
                        )
                        if cursor.rowcount == 1:
                            logging.info(f"File record (ID: {file_id}) deleted successfully by owner (ID: {user_id}).")
                            return file_name, owner_id, file_record['is_public']
                        else:
                            logging.warning(f"File ID {file_id} not found or user {user_id} is not the owner.")
                            return None, None, None
                except Exception as e:
                    logging.error(f"Failed to delete file record: {e}", exc_info=True)
                    return None, None, None
            