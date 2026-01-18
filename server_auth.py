import bcrypt
import uuid
import logging
import threading
from user_management import DatabaseManager
from datetime import datetime

class ServerAuthHandler:
    def __init__(self, db_manager: DatabaseManager, config):
        self.db_manager = db_manager
        self.sessions = {}
        self.session_lock = threading.Lock()
        self.config = config
        
        # Pull constants from config for consistency
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
        """Registers a new user via the db_manager."""
        try:
            if not username or not password:
                return self.REGISTER_FAILED_RESPONSE
            
            if self.db_manager.get_user_record(username=username):
                logging.warning(f"Registration failed: User '{username}' already exists.")
                return self.REGISTER_FAILED_RESPONSE
            
            if self.db_manager.create_user(username, password):
                logging.info(f"User '{username}' registered successfully.")
                return self.REGISTER_SUCCESS_RESPONSE
            return self.REGISTER_FAILED_RESPONSE
        except Exception as e:
            logging.error(f"Registration Error: {e}")
            return f"{self.ERROR_RESPONSE}{self.separator}{str(e)}"

    def login_user(self, username, password):
        """Authenticates user and returns the full 5-part success string."""
        try:
            user = self.db_manager.get_user_record(username=username)
            
            if user and bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
                session_id = str(uuid.uuid4())
                
                with self.session_lock:
                    self.sessions[session_id] = {
                        'username': username, 
                        'role': user['role'], 
                        'user_id': user['id']
                    }
                
                self.db_manager.update_user_record(user['id'], session_id=session_id)

                logging.info(f"User '{username}' (ID: {user['id']}) logged in.")
                
                return (f"{self.LOGIN_SUCCESS_RESPONSE}{self.separator}"
                        f"{session_id}{self.separator}"
                        f"{username}{self.separator}"
                        f"{user['role']}{self.separator}"
                        f"{user['id']}")
            
            logging.warning(f"Failed login attempt for username: {username}")
            return self.LOGIN_FAILED_RESPONSE

        except Exception as e:
            logging.error(f"Login Error: {e}")
            return self.LOGIN_FAILED_RESPONSE

    def logout_user(self, session_id):
        """Removes session and clears it from DB."""
        with self.session_lock:
            session_data = self.sessions.pop(session_id, None)
        
        if session_data:
            self.db_manager.update_user_record(session_data['user_id'], session_id=None)
            logging.info(f"User '{session_data['username']}' logged out.")
            return self.LOGOUT_SUCCESS_RESPONSE
        return self.INVALID_SESSION_RESPONSE

    def is_valid_session(self, session_id):
        """Check if session exists in memory."""
        with self.session_lock:
            return session_id in self.sessions

    def get_session_data(self, session_id):
        """Returns the full session dict: username, role, user_id."""
        with self.session_lock:
            return self.sessions.get(session_id)