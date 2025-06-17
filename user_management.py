import sqlite3
import bcrypt

class UserDatabaseManager:
    def __init__(self, db_path="users.db"):
        self.db_path = db_path
        self._create_users_table()

    def _get_db_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row # Allows accessing columns by name
        return conn

    def _create_users_table(self):
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user', -- 'user' or 'admin'
                session_id TEXT UNIQUE NULL,
                last_login TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
        print(f"User database initialized at {self.db_path}")
        self._create_default_admin_if_not_exists()

    def _create_default_admin_if_not_exists(self):
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", ("admin",))
        admin_exists = cursor.fetchone()
        conn.close()

        if not admin_exists:
            print("No admin user found. Creating default admin user (username: admin, password: adminpass)")
            hashed_password = bcrypt.hashpw("adminpass".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            self.add_user("admin", hashed_password, "admin")
        else:
            print("Default admin user already exists.")

    def add_user(self, username, password_hash, role='user'):
        conn = self._get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                           (username, password_hash, role))
            conn.commit()
            print(f"User '{username}' ({role}) added successfully.")
            return True
        except sqlite3.IntegrityError:
            print(f"Error: Username '{username}' already exists.")
            return False
        except Exception as e:
            print(f"Error adding user '{username}': {e}")
            return False
        finally:
            conn.close()

    def verify_user(self, username, password_plain):
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, password_hash, role FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        conn.close()

        if user:
            stored_password_hash = user['password_hash']
            if isinstance(stored_password_hash, str):
                stored_password_hash = stored_password_hash.encode('utf-8')

            if bcrypt.checkpw(password_plain.encode('utf-8'), stored_password_hash):
                print(f"User '{username}' authenticated successfully.")
                return dict(user) # Return user as a dict for easier access
        print(f"Authentication failed for user '{username}'.")
        return None

    def update_session(self, user_id, new_session_id):
        conn = self._get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE users SET session_id = ?, last_login = CURRENT_TIMESTAMP WHERE id = ?",
                           (new_session_id, user_id))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error updating session for user_id {user_id}: {e}")
            return False
        finally:
            conn.close()

    def get_user_by_session_id(self, session_id):
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, role, session_id FROM users WHERE session_id = ?", (session_id,))
        user = cursor.fetchone()
        conn.close()
        return dict(user) if user else None

    def clear_session(self, session_id):
        conn = self._get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE users SET session_id = NULL WHERE session_id = ?", (session_id,))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error clearing session {session_id}: {e}")
            return False
        finally:
            conn.close()