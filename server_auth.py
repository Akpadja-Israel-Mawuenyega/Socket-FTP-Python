import bcrypt
import uuid
import os
import socket
import shutil
from user_management import UserDatabaseManager

# This class will encapsulate authentication and authorization logic for the server side
class ServerAuthHandler:
    def __init__(self, db_manager: UserDatabaseManager, separator: str, public_files_dir: str):
        self.db_manager = db_manager
        self.separator = separator
        self.public_files_dir = "public_files"

        # Authentication and Authorization Responses
        self.REGISTER_SUCCESS_RESPONSE = "REGISTER_SUCCESS"
        self.REGISTER_FAILED_RESPONSE = "REGISTER_FAILED"
        self.LOGIN_SUCCESS_RESPONSE = "LOGIN_SUCCESS"
        self.LOGIN_FAILED_RESPONSE = "LOGIN_FAILED"
        self.LOGOUT_SUCCESS_RESPONSE = "LOGOUT_SUCCESS"
        self.AUTHENTICATION_REQUIRED_RESPONSE = "AUTH_REQUIRED"
        self.PERMISSION_DENIED_RESPONSE = "PERMISSION_DENIED"
        self.ADMIN_FILE_MAKE_PUBLIC_SUCCESS = "ADMIN_PUBLIC_SUCCESS"
        self.ADMIN_FILE_MAKE_PUBLIC_FAILED = "ADMIN_PUBLIC_FAILED"
        self.INVALID_SESSION_RESPONSE = "INVALID_SESSION"
        self.FILE_NOT_FOUND_RESPONSE = "FILE_NOT_FOUND" # For admin public command
        
        print(f"Server's configured public files directory: {os.path.abspath(self.public_files_dir)}")


    def authenticate_session(self, session_id: str) -> dict:
        """
        Validates the session ID and returns the user's details if valid.
        Returns None if the session is invalid or expired.
        """
        if not session_id:
            return None
        user = self.db_manager.get_user_by_session_id(session_id)
        return user

    def _send_response(self, client_socket: socket.socket, response: str):
        # Helper to send encoded response.
        try:
            client_socket.sendall(response.encode('utf-8'))
        except (BrokenPipeError, ConnectionResetError) as e:
            print(f"Error sending response: Client connection lost. {e}")
        except Exception as e:
            print(f"Error sending response: {e}")

    def handle_register(self, client_socket: socket.socket, username: str, password_plain: str):
        print(f"Attempting to register user: {username}")
        # Hash the password before storing
        hashed_password = bcrypt.hashpw(password_plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        if self.db_manager.add_user(username, hashed_password):
            self._send_response(client_socket, self.REGISTER_SUCCESS_RESPONSE)
        else:
            self._send_response(client_socket, f"{self.REGISTER_FAILED_RESPONSE}{self.separator}Username already exists or other DB error.")

    def handle_login(self, client_socket: socket.socket, username: str, password_plain: str):
        print(f"Attempting to log in user: {username}")
        user = self.db_manager.verify_user(username, password_plain)
        if user:
            # Generate a new session ID
            session_id = uuid.uuid4().hex
            if self.db_manager.update_session(user['id'], session_id):
                response_data = f"{self.LOGIN_SUCCESS_RESPONSE}{self.separator}{session_id}{self.separator}{user['role']}"
                self._send_response(client_socket, response_data)
                print(f"User '{username}' logged in successfully with session ID: {session_id[:8]}...")
            else:
                self._send_response(client_socket, f"{self.LOGIN_FAILED_RESPONSE}{self.separator}Could not create session.")
        else:
            self._send_response(client_socket, f"{self.LOGIN_FAILED_RESPONSE}{self.separator}Invalid username or password.")

    def handle_logout(self, client_socket: socket.socket, session_id: str):
        print(f"Attempting to log out session: {session_id[:8]}...")
        if self.db_manager.clear_session(session_id):
            self._send_response(client_socket, self.LOGOUT_SUCCESS_RESPONSE)
            print(f"Session {session_id[:8]}... logged out.")
        else:
            self._send_response(client_socket, f"ERROR{self.separator}Failed to clear session.")

    def handle_make_file_public_admin(self, client_socket: socket.socket, current_user: dict, full_source_path: str): # <--- Renamed 'filename' to 'full_source_path' for clarity
        print(f"User {current_user['username']} ({current_user['role']}) attempting to make '{full_source_path}' public.")
        if current_user['role'] != 'admin':
            self._send_response(client_socket, self.PERMISSION_DENIED_RESPONSE)
            print(f"Permission denied for {current_user['username']} to make '{full_source_path}' public.")
            return
        
        filepath = full_source_path
        file_basename = os.path.basename(filepath)
        public_filepath = os.path.join(self.public_files_dir, file_basename)

        print(f"Attempting to move FROM: {filepath}")
        print(f"Attempting to move TO: {public_filepath}")

        if not os.path.exists(filepath):
            self._send_response(client_socket, f"{self.ADMIN_FILE_MAKE_PUBLIC_FAILED}{self.separator}Source file not found on server.")
            print(f"Admin file make public failed: Source file '{filepath}' not found.")
            return
        if not os.path.isfile(filepath):
            self._send_response(client_socket, f"{self.ADMIN_FILE_MAKE_PUBLIC_FAILED}{self.separator}Source is not a file.")
            print(f"Admin file make public failed: Source '{filepath}' is not a file (it might be a directory).")
            return

        try:
            os.makedirs(os.path.dirname(public_filepath), exist_ok=True)
            
            shutil.move(filepath, public_filepath)

            self._send_response(client_socket, f"{self.ADMIN_FILE_MAKE_PUBLIC_SUCCESS}{self.separator}{file_basename}")
            print(f"Admin '{file_basename}' successfully moved to public files from '{filepath}' by {current_user['username']}.")
        except shutil.Error as e: 
            self._send_response(client_socket, f"{self.ADMIN_FILE_MAKE_PUBLIC_FAILED}{self.separator}Server error during move: {e}")
            print(f"Admin file make public failed for '{file_basename}': Shutil error - {e}")
        except Exception as e:
            self._send_response(client_socket, f"{self.ADMIN_FILE_MAKE_PUBLIC_FAILED}{self.separator}Server error: {e}")
            print(f"Admin file make public failed for '{file_basename}': Unexpected error - {e}")
