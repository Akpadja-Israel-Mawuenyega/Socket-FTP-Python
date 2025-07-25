import pymysql.cursors
import logging
import bcrypt
from pymysql.err import IntegrityError
import sys
import os
import configparser

class DatabaseManager:
    def __init__(self, db_config_parser):
        self.db_config = {
            'host': db_config_parser['DB_HOST'],
            'user': db_config_parser['DB_USER'],
            'password': os.getenv('DB_PASSWORD', db_config_parser['DB_PASSWORD']),
            'db': db_config_parser['DB_NAME'],
            'autocommit': True,
            'cursorclass': pymysql.cursors.DictCursor,
            'charset': 'utf8mb4'
        }
        try:
            self._get_db_connection()
            logging.info("Database connection pool initialized.")
        except Exception as e:
            logging.critical(f"Error initializing MySQL connection pool: {e}", exc_info=True)
            sys.exit(1)

    def _get_db_connection(self):
        return pymysql.connect(**self.db_config)
    
    def create_user_table_if_not_exists(self):
        conn = None
        try:
            conn = self._get_db_connection()
            with conn.cursor() as cursor:
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
            conn.commit()
            logging.info("User database table ensured in 'ftp_users'.")
        except Exception as e:
            logging.critical(f"Error creating user table: {e}", exc_info=True)
        finally:
            if conn:
                conn.close()

    def register_user(self, username, password, role='user'):
        conn = None
        try:
            password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            conn = self._get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)", (username, password_hash, role))
            conn.commit()
            return True
        except IntegrityError:
            logging.warning(f"Registration failed: Username '{username}' already exists.")
            return False
        except pymysql.Error as e:
            logging.error(f"Error registering user '{username}': {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()

    def get_user_by_username(self, username):
        conn = None
        try:
            conn = self._get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT id, username, password_hash, role, session_id FROM users WHERE username = %s", (username,))
                result = cursor.fetchone()
                return result
        except pymysql.Error as e:
            logging.error(f"Error getting user by username '{username}': {e}", exc_info=True)
            return None
        finally:
            if conn:
                conn.close()

    def update_user_session(self, user_id, session_id):
        conn = None
        try:
            conn = self._get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("UPDATE users SET session_id = %s WHERE id = %s", (session_id, user_id))
            conn.commit()
        except pymysql.Error as e:
            logging.error(f"Error updating session for user ID '{user_id}': {e}", exc_info=True)
        finally:
            if conn:
                conn.close()

    def update_user_session_by_username(self, username, session_id):
        conn = None
        try:
            conn = self._get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("UPDATE users SET session_id = %s WHERE username = %s", (session_id, username))
            conn.commit()
        except pymysql.Error as e:
            logging.error(f"Error updating session for user '{username}': {e}", exc_info=True)
        finally:
            if conn:
                conn.close()