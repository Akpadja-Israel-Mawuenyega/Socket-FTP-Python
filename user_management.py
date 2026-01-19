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
                        is_public BOOLEAN DEFAULT FALSE,
                        recipient_id INT NULL,
                        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (owner_id) REFERENCES users(id),
                        FOREIGN KEY (recipient_id) REFERENCES users(id)
                    )
                    """
                    cursor.execute(create_table_sql)
                    logging.info("Files database table ensured.")
                except Exception as e:
                    logging.critical(f"Error creating files table: {e}", exc_info=True)        
            
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

    def create_user(self, username, password, role='user'):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
                    cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)", (username, password_hash, role))
                    return True
                except IntegrityError:
                    logging.warning(f"User account creation failed: Username '{username}' already exists.")
                    return False
                except pymysql.Error as e:
                    logging.error(f"Error creating user '{username}': {e}", exc_info=True)
                    return False             
    
    def get_user_record(self, user_id=None, username=None):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    if user_id:
                        query = f"SELECT * FROM users WHERE id = %s"
                        params = (user_id,)
                    elif username:
                        query = f"SELECT * FROM users WHERE username = %s"
                        params = (username,)
                    else:
                        return None
                
                    cursor.execute(query, params)
                    return cursor.fetchone()
                except pymysql.Error as e:
                    logging.error(f"Error fetching user record: {e}")
                    return None      
    
    def add_file_record(self, owner_id, file_name, file_size, is_public=False, recipient_id=None):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    sql = """
                        INSERT INTO files (owner_id, file_name, file_size, is_public, recipient_id)
                        VALUES (%s, %s, %s, %s, %s)
                    """
                    cursor.execute(sql, (owner_id, file_name, file_size , is_public, recipient_id))
                    logging.info(f"File record for '{file_name}' added (Public: {is_public}.")
                    return True
                except Exception as e:
                    logging.error(f"Failed to add file record for {file_name}: {e}.")
                    return False
                
    def get_files(self, owner_id=None, is_public=None, recipient_id=None, exclude_recipient=False):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    query = "SELECT file_id, file_name, file_size, owner_id FROM files WHERE 1=1"
                    params = []

                    if owner_id is not None:
                        query += " AND owner_id = %s"
                        params.append(owner_id)

                    if recipient_id is not None:
                        query += " AND recipient_id = %s"
                        params.append(recipient_id)
                    elif exclude_recipient: 
                        query += " AND recipient_id IS NULL"

                    if is_public is not None:
                        query += " AND is_public = %s"
                        params.append(is_public)

                    cursor.execute(query, tuple(params))
                    return cursor.fetchall()
                except Exception as e:
                    logging.error(f"Failed to get file list: {e}")
                    return []
        
    def get_file_record(self, file_id=None, file_name=None, owner_id=None, recipient_id=None, is_public=None):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    query = "SELECT * FROM files WHERE 1=1"
                    params = []
                    if file_id:
                        query += " AND file_id = %s"
                        params.append(file_id)
                    if file_name:
                        query += " AND file_name = %s"
                        params.append(file_name)
                    if owner_id:
                        query += " AND owner_id = %s"
                        params.append(owner_id)
                    if recipient_id:
                        query += " AND recipient_id = %s"
                        params.append(recipient_id)
                    if is_public is not None:
                        query += " AND is_public = %s"
                        params.append(is_public)
                    
                    cursor.execute(query, tuple(params))
                    return cursor.fetchone()
                except pymysql.Error as e:
                    logging.error(f"Error fecthing file record: {e}")
                    return None                   
    
    def update_file_record(self, file_id, owner_id=None, is_public=None, recipient_id=None):
        updates = []
        params = []

        if is_public is not None:
            updates.append("is_public = %s")
            params.append(is_public)
        
        # Allow recipient_id to be updated independently
        if recipient_id is not None:
            updates.append("recipient_id = %s")
            params.append(recipient_id)
            
        if owner_id is not None:
            updates.append("owner_id = %s")
            params.append(owner_id)    

        if not updates:
            return False

        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    sql = f"UPDATE files SET {', '.join(updates)} WHERE file_id = %s"
                    params.append(file_id)
                    cursor.execute(sql, tuple(params))
                    return cursor.rowcount > 0
                except Exception as e:
                    logging.error(f"Database error updating file {file_id}: {e}")
                    return False
                    
    def update_user_record(self, user_id, username=None, password=None, session_id=None):
        """
        Generic user update. Dynamically builds the SET clause based on provided args.
        Supports updating password (with hashing), and session_id.
        """
        updates = []
        params = []

        if username:
            updates.append("username = %s")
            params.append(username)
                
        if password:
            hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            updates.append("password_hash = %s")
            params.append(hashed)
        
        if session_id is not None:
            updates.append("session_id = %s")
            params.append(session_id)

        if not updates:
            return False

        sql = f"UPDATE users SET {', '.join(updates)} WHERE id = %s"
        params.append(user_id)

        try:
            with self.db_pool.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, tuple(params))
                    return cursor.rowcount > 0
        except Exception as e:
            logging.error(f"Database error updating user {user_id}: {e}")
            return False
    
    def delete_file_record(self, file_id, owner_id=None):
        with self.db_pool.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    query = "DELETE FROM files WHERE file_id = %s"
                    params = [file_id]
                    
                    if owner_id:
                        query += " AND owner_id = %s"
                        params.append(owner_id)
                        
                    cursor.execute(query, tuple(params))
                    success = cursor.rowcount == 1
                    
                    if success:
                        logging.info(f"Successfully delete file record with ID {file_id}.")
                    else:
                        logging.warning(f"Delete attempted for file ID {file_id}, but no record was matched.")
                    return success
                                
                except Exception as e:
                    logging.error(f"Database error during file deletion (ID: {file_id}): {e}")
                    return False
                
    def close_pool(self):
        """Manually dispose all connections in the pool"""
        if self.db_pool:
            try:     
                self.db_pool = None           
                logging.info("Database connection pool disposed.")
            except Exception as e:
                logging.error(f"Error disposing connection pool: {e}")