import bcrypt
import uuid
import logging
from user_management import DatabaseManager
from datetime import datetime

class ServerAuthHandler:
    def __init__(self, db_manager: DatabaseManager, config):
        self.db_manager = db_manager
        self.sessions = {}  # In-memory session store: {session_id: username}
        self.config = config
        self.REGISTER_COMMAND = self.config['COMMANDS']['REGISTER']
        self.LOGIN_COMMAND = self.config['COMMANDS']['LOGIN']
        self.LOGOUT_COMMAND = self.config['COMMANDS']['LOGOUT']
        self.REGISTER_SUCCESS_RESPONSE = self.config['RESPONSES']['REGISTER_SUCCESS']
        self.REGISTER_FAILED_RESPONSE = self.config['RESPONSES']['REGISTER_FAILED']
        self.LOGIN_SUCCESS_RESPONSE = self.config['RESPONSES']['LOGIN_SUCCESS']
        self.LOGIN_FAILED_RESPONSE = self.config['RESPONSES']['LOGIN_FAILED']
        self.LOGOUT_SUCCESS_RESPONSE = self.config['RESPONSES']['LOGOUT_SUCCESS']
        self.INVALID_SESSION_RESPONSE = self.config['RESPONSES']['INVALID_SESSION']
        self.PERMISSION_DENIED_RESPONSE = self.config['RESPONSES']['PERMISSION_DENIED']
        self.ERROR_RESPONSE = self.config['RESPONSES']['ERROR']
        self.separator = self.config['SERVER']['SEPARATOR']

    def register_user(self, username, password):
        try:
            if not username or not password:
                logging.warning("Registration failed: Username or password was empty.")
                return self.REGISTER_FAILED_RESPONSE
            
            if self.db_manager.get_user_by_username(username):
                logging.warning(f"Registration failed: Username '{username}' already exists.")
                return self.REGISTER_FAILED_RESPONSE
            
            success = self.db_manager.register_user(username, password)
            if success:
                logging.info(f"User '{username}' registered successfully.")
                return self.REGISTER_SUCCESS_RESPONSE
            else:
                logging.warning(f"Registration failed for user '{username}' due to internal error.")
                return self.REGISTER_FAILED_RESPONSE
        except Exception as e:
            logging.error(f"Error during user registration: {e}", exc_info=True)
            return f"{self.ERROR_RESPONSE}{self.separator}{str(e)}"

    def login_user(self, username, password):
        try:
            if not username or not password:
                logging.warning(f"Login failed for user '{username}': Missing username or password.")
                return self.LOGIN_FAILED_RESPONSE
            
            user = self.db_manager.get_user_by_username(username)
            if user and bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
                session_id = str(uuid.uuid4())
                self.db_manager.update_user_session(user['id'], session_id)
                self.sessions[session_id] = {'username': username, 'role': user['role']}

                logging.info(f"User '{username}' logged in successfully.")
                return f"{self.LOGIN_SUCCESS_RESPONSE}{self.separator}{session_id}{self.separator}{username}{self.separator}{user['role']}"
            
            logging.warning(f"Login failed for user '{username}': Invalid credentials.")
            return self.LOGIN_FAILED_RESPONSE
        except Exception as e:
            logging.error(f"Error during user login: {e}", exc_info=True)
            return f"{self.ERROR_RESPONSE}{self.separator}{str(e)}"

    def logout_user(self, session_id):
        if session_id in self.sessions:
            session_data = self.sessions.pop(session_id)
            username = session_data['username']
            self.db_manager.update_user_session_by_username(username, None)
            logging.info(f"User '{username}' logged out successfully.")
            return self.LOGOUT_SUCCESS_RESPONSE
        else:
            return self.INVALID_SESSION_RESPONSE

    def is_valid_session(self, session_id):
        return session_id in self.sessions

    def get_username_from_session(self, session_id):
        session_data = self.sessions.get(session_id)
        return session_data['username'] if session_data else None

    def get_user_role(self, username):
        user = self.db_manager.get_user_by_username(username)
        return user['role'] if user else 'guest'
    
    def get_session_data(self, session_id):
        return self.sessions.get(session_id)
    