import threading
import socket
import tqdm
import shutil
import os
import sys
import logging
import ssl
from server_auth import ServerAuthHandler
import json
import base64
from concurrent.futures import ThreadPoolExecutor

class ClientHandler(threading.Thread):
    def __init__(self, client_socket: socket.socket, address: tuple, server_config: dict, auth_handler: ServerAuthHandler):
        threading.Thread.__init__(self)
        self.client_socket = client_socket
        self.address = address
        self.config = server_config
        self.auth_handler = auth_handler
        self.upload_dir = self.config['SERVER']['UPLOAD_DIR']
        self.public_files_dir = self.config['SERVER']['PUBLIC_FILES_DIR']
        self.shared_uploads_dir = self.config['SERVER']['SHARED_UPLOADS_DIR']
        self.buffer_size = self.config['SERVER'].getint('BUFFER_SIZE')
        self.separator = self.config['SERVER']['SEPARATOR']
        self.session_id = None
        self.username = None
        self.user_role = None
        self.executor = ThreadPoolExecutor(max_workers=5)
        logging.info(f"[{self.address}] Client handler initialized.")

    def run(self):
        try:
            self._handle_client_connection()
        except (socket.error, ConnectionResetError) as e:
            logging.warning(f"[{self.address}] Connection lost: {e}")
        finally:
            self._cleanup()

    def _handle_client_connection(self):
        logging.info(f"[{self.address}] Waiting for commands.")
        while True:
            try:
                command_raw = self.client_socket.recv(self.buffer_size)
                if not command_raw:
                    break
                
                command_str = command_raw.decode('utf-8').strip()
                if not command_str:
                    continue
                
                logging.info(f"[{self.address}] Received raw command: '{command_str}'")
                
                parts = command_str.split(self.separator)
                command = parts[0]
                
                # --- Authentication Commands ---
                if command == self.auth_handler.REGISTER_COMMAND:
                    if len(parts) >= 3:
                        username = parts[1]
                        password = parts[2]
                        response = self.auth_handler.register_user(username, password)
                        self._send_response(response)
                    else:
                        self._send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Invalid REGISTER command format.")
                
                elif command == self.auth_handler.LOGIN_COMMAND:
                    if len(parts) >= 3:
                        username = parts[1]
                        password = parts[2]
                        response = self.auth_handler.login_user(username, password)
                        self._send_response(response)
                        if response.startswith(self.auth_handler.LOGIN_SUCCESS_RESPONSE):
                            _response, self.session_id, self.username, self.user_role = response.split(self.separator)
                            user_dir = os.path.join(self.upload_dir, self.username)
                            os.makedirs(user_dir, exist_ok=True)
                    else:
                        self._send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Invalid LOGIN command format.")
                
                elif command == self.auth_handler.LOGOUT_COMMAND:
                    if len(parts) >= 2 and parts[1] == self.session_id:
                        response = self.auth_handler.logout_user(self.session_id)
                        self._send_response(response)
                        self.session_id = None
                        self.username = None
                        self.user_role = None
                    else:
                        self._send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Invalid session or command format.")
                
                elif command == self.config['COMMANDS']['QUIT']:
                    logging.info(f"[{self.address}] Client requested to quit.")
                    self.auth_handler.logout_user(self.session_id)
                    break

                # --- File Transfer Commands ---
                elif command == self.config['COMMANDS']['UPLOAD_PRIVATE']:
                    if len(parts) >= 4 and self.auth_handler.is_valid_session(parts[1]):
                        file_name = parts[2]
                        file_size_str = parts[3]
                        self._handle_upload_file(file_name, file_size_str, private=True)
                    else:
                        self._send_response(self.auth_handler.INVALID_SESSION_RESPONSE)

                elif command == self.config['COMMANDS']['UPLOAD_FOR_SHARING']:
                    if len(parts) >= 4 and self.auth_handler.is_valid_session(parts[1]):
                        file_name = parts[2]
                        file_size_str = parts[3]
                        self._handle_upload_file(file_name, file_size_str, private=False)
                    else:
                        self._send_response(self.auth_handler.INVALID_SESSION_RESPONSE)

                elif command == self.config['COMMANDS']['DOWNLOAD_PRIVATE']:
                    if len(parts) >= 3 and self.auth_handler.is_valid_session(parts[1]):
                        file_name = parts[2]
                        self._handle_download_file(file_name, from_private=True)
                    else:
                        self._send_response(self.auth_handler.INVALID_SESSION_RESPONSE)

                elif command == self.config['COMMANDS']['LIST_PRIVATE']:
                    if len(parts) >= 2 and self.auth_handler.is_valid_session(parts[1]):
                        self._handle_list_private()
                    else:
                        self._send_response(self.auth_handler.INVALID_SESSION_RESPONSE)

                elif command == self.config['COMMANDS']['DOWNLOAD_SERVER_PUBLIC']:
                    if len(parts) >= 2:
                        file_name = parts[1]
                        self._handle_download_file(file_name, from_public=True)
                    else:
                        self._send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Invalid DOWNLOAD_SERVER_PUBLIC command format.")

                elif command == self.config['COMMANDS']['DOWNLOAD_SHARED']:
                    if len(parts) >= 3 and self.auth_handler.is_valid_session(parts[1]):
                        owner_and_file_name = parts[2]
                        self._handle_download_file(owner_and_file_name, from_public=False)
                    else:
                        self._send_response(self.auth_handler.INVALID_SESSION_RESPONSE)

                elif command == self.config['COMMANDS']['LIST_SHARED']:
                    if len(parts) >= 2 and self.auth_handler.is_valid_session(parts[1]):
                        self.list_shared_files()
                    else:
                        self._send_response(self.auth_handler.INVALID_SESSION_RESPONSE)
                
                # --- Admin/User Commands ---
                elif command == self.config['COMMANDS']['MAKE_PUBLIC_ADMIN']:
                    if len(parts) >= 4 and self.auth_handler.is_valid_session(parts[1]):
                        owner_path = parts[2]
                        owner_parts= owner_path.split('/')
                        owner_username = owner_parts[0]
                        logging.info(owner_username)
                        file_name = parts[3]
                        session_data = self.auth_handler.get_session_data(parts[1])
                        if session_data and session_data['role'] == 'admin':
                            self.make_public_admin(owner_username, file_name)
                        else:
                            self._send_response(self.auth_handler.PERMISSION_DENIED_RESPONSE)
                    else:
                        self._send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Invalid MAKE_PUBLIC_ADMIN command format.")
                
                elif command == self.config['COMMANDS']['MAKE_PUBLIC_USER']:
                    if len(parts) >= 3 and self.auth_handler.is_valid_session(parts[1]):
                        file_name = parts[2]
                        if self.user_role in ['user', 'admin']:
                            self.make_public_user(file_name)
                        else:
                            self._send_response(self.auth_handler.PERMISSION_DENIED_RESPONSE)
                    else:
                        self._send_response(self.auth_handler.INVALID_SESSION_RESPONSE)
                        
                elif command == self.config['COMMANDS']['MAKE_SHARED_USER']:
                    if len(parts) >= 3 and self.auth_handler.is_valid_session(parts[1]):
                        file_name = parts[2]
                        if self.user_role in ['user', 'admin']:
                            self.make_shared_user(file_name)
                        else:
                            self._send_response(self.auth_handler.PERMISSION_DENIED_RESPONSE)
                    else:
                        self._send_response(self.auth_handler.INVALID_SESSION_RESPONSE)        
                                    
            except IndexError:
                logging.error(f"[{self.address}] Malformed command received: {command_str}")
                self._send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Malformed command.")
            except Exception as e:
                logging.error(f"[{self.address}] An unexpected error occurred: {e}", exc_info=True)
                self._send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}An internal server error occurred.")

    def _send_response(self, response):
        try:
            self.client_socket.sendall(response.encode('utf-8'))
        except (socket.error, ConnectionResetError) as e:
            logging.warning(f"[{self.address}] Failed to send response: {e}")

    def _cleanup(self):
        if self.client_socket:
            self.client_socket.close()
        logging.info(f"[{self.address}] Disconnected.")

    def _handle_upload_file(self, file_name, file_size_str, private):
        try:
            file_size = int(file_size_str)
            target_dir = os.path.join(self.upload_dir, self.username) if private else os.path.join(self.shared_uploads_dir, self.username)
            os.makedirs(target_dir, exist_ok=True)
            file_path = os.path.join(target_dir, file_name)

            self._send_response(f"{self.config['RESPONSES']['READY_FOR_DATA']}{self.separator}{file_name}{self.separator}{file_size_str}")

            with open(file_path, "wb") as f:
                with tqdm.tqdm(total=file_size, unit="B", unit_scale=True, unit_divisor=1024, desc=f"Receiving {file_name}") as progress:
                    bytes_received = 0
                    while bytes_received < file_size:
                        bytes_to_read = min(self.buffer_size, file_size - bytes_received)
                        bytes_read = self.client_socket.recv(bytes_to_read)
                        if not bytes_read:
                            break
                        f.write(bytes_read)
                        bytes_received += len(bytes_read)
                        progress.update(len(bytes_read))
            
            logging.info(f"[{self.address}] File '{file_name}' uploaded successfully to {target_dir}.")
            self._send_response(self.config['RESPONSES']['UPLOAD_DONE'])
        except Exception as e:
            logging.error(f"[{self.address}] Error during file upload: {e}", exc_info=True)
            self._send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Error during file upload.")

    def _handle_download_file(self, file_identifier, from_private=False, from_public=False):
        if from_private:
            safe_file_name = os.path.basename(file_identifier)
            file_path = os.path.join(self.upload_dir, self.username, safe_file_name)
            original_file_name = safe_file_name
        elif from_public:
            safe_file_name = os.path.basename(file_identifier)
            file_path = os.path.join(self.public_files_dir, safe_file_name)
            original_file_name = safe_file_name
        else:
            try:
                owner_username, original_file_name = file_identifier.split('/', 1)
                safe_owner_username = os.path.basename(owner_username)
                safe_file_name = os.path.basename(original_file_name)
                file_path = os.path.join(self.shared_uploads_dir, safe_owner_username, safe_file_name)
            except ValueError:
                self._send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Invalid shared file identifier format. Use owner/filename.")
                return

        if not os.path.isfile(file_path):
            self._send_response(self.config['RESPONSES']['FILE_NOT_FOUND'])
            logging.warning(f"[{self.address}] File '{file_path}' not found for download.")
            return
        
        try:
            file_size = os.path.getsize(file_path)
            self._send_response(f"{self.config['RESPONSES']['DOWNLOAD_READY']}{self.separator}{original_file_name}{self.separator}{file_size}")

            with open(file_path, "rb") as f:
                with tqdm.tqdm(total=file_size, unit="B", unit_scale=True, unit_divisor=1024, desc=f"Sending {original_file_name}") as progress:
                    while True:
                        bytes_read = f.read(self.buffer_size)
                        if not bytes_read:
                            break
                        self.client_socket.sendall(bytes_read)
                        progress.update(len(bytes_read))
            
            logging.info(f"[{self.address}] File '{original_file_name}' sent successfully.")
            self._send_response(self.config['RESPONSES']['DOWNLOAD_COMPLETE'])
        except Exception as e:
            logging.error(f"[{self.address}] Error during file download: {e}", exc_info=True)
            self._send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Error during file download.")

    def _handle_list_private(self):
        try:
            user_dir = os.path.join(self.upload_dir, self.username)
            if not os.path.exists(user_dir):
                self._send_response(self.config['RESPONSES']['NO_FILES_PRIVATE'])
                return
            
            files = [f for f in os.listdir(user_dir) if os.path.isfile(os.path.join(user_dir, f))]
            if files:
                response = f"{self.config['RESPONSES']['PRIVATE_LIST']}{self.separator}{self.separator.join(files)}"
                self._send_response(response)
            else:
                self._send_response(self.config['RESPONSES']['NO_FILES_PRIVATE'])
            logging.info(f"[{self.address}] Listed private files for user '{self.username}'.")
        except Exception as e:
            logging.error(f"[{self.address}] Error listing private files: {e}", exc_info=True)
            self._send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}{str(e)}")

    def list_shared_files(self):
        try:
            all_shared_files = []
            for root, dirs, files in os.walk(self.shared_uploads_dir):
                for file_name in files:
                    relative_path = os.path.relpath(os.path.join(root, file_name), self.shared_uploads_dir)
                    # This is the key line, formatting the output as 'owner/filename'
                    all_shared_files.append(relative_path.replace(os.sep, '/'))

            if all_shared_files:
                response = f"{self.config['RESPONSES']['SHARED_LIST']}{self.separator}{self.separator.join(all_shared_files)}"
                self._send_response(response)
            else:
                self._send_response(self.config['RESPONSES']['NO_FILES_SHARED'])
            logging.info(f"[{self.address}] Listed shared files.")
        except Exception as e:
            logging.error(f"[{self.address}] Error listing shared files: {e}", exc_info=True)
            self._send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}{str(e)}")


    def make_public_admin(self, owner_username, file_name):
        safe_owner_username = os.path.basename(owner_username)
        safe_file_name = os.path.basename(file_name)

        private_file_path = os.path.join(self.upload_dir, safe_owner_username, safe_file_name)
        shared_file_path = os.path.join(self.shared_uploads_dir, safe_owner_username, safe_file_name)

        source_file_path = None
        if os.path.isfile(private_file_path):
            source_file_path = private_file_path
            logging.debug(f"[{self.address}] Found file in '{safe_owner_username}' private folder: {source_file_path}")
        elif os.path.isfile(shared_file_path):
            source_file_path = shared_file_path
            logging.debug(f"[{self.address}] Found file in '{safe_owner_username}' shared folder: {source_file_path}")

        if source_file_path:
            public_file_path = os.path.join(self.public_files_dir, safe_file_name)
            try:
                shutil.copy2(source_file_path, public_file_path)
                self._send_response(self.config['RESPONSES']['ADMIN_PUBLIC_SUCCESS'])
                logging.info(f"[{self.address}] Admin copied '{safe_file_name}' from '{safe_owner_username}' to public.")
            except Exception as e:
                logging.error(f"[{self.address}] Error copying file: {e}", exc_info=True)
                self._send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}{str(e)}")
        else:
            logging.warning(f"[{self.address}] Admin tried to make a non-existent file '{safe_file_name}' from '{safe_owner_username}' public.")
            self._send_response(self.config['RESPONSES']['FILE_NOT_FOUND'])

    def make_public_user(self, file_name):
        safe_file_name = os.path.basename(file_name)
        private_file_path = os.path.join(self.upload_dir, self.username, safe_file_name)
        
        logging.debug(f"[{self.address}] Checking for file in user's private folder: {private_file_path}")

        if os.path.isfile(private_file_path):
            public_file_path = os.path.join(self.public_files_dir, safe_file_name)
            try:
                shutil.copy2(private_file_path, public_file_path)
                self._send_response(self.config['RESPONSES']['USER_PUBLIC_SUCCESS'])
                logging.info(f"[{self.address}] User '{self.username}' made file '{safe_file_name}' public.")
            except Exception as e:
                logging.error(f"[{self.address}] Error copying file: {e}", exc_info=True)
                self._send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}{str(e)}")
        else:
            logging.warning(f"[{self.address}] User '{self.username}' tried to make a non-existent file public: '{safe_file_name}'.")
            self._send_response(self.config['RESPONSES']['FILE_NOT_FOUND'])
            
    def make_shared_user(self, file_name):
        safe_file_name = os.path.basename(file_name)
        private_file_path = os.path.join(self.upload_dir, self.username, safe_file_name)
        logging.debug(f"[{self.address}] Checking for file in user's private folder: {private_file_path}")

        if os.path.isfile(private_file_path):
            user_shared_dir = os.path.join(self.shared_uploads_dir, self.username)
            os.makedirs(user_shared_dir, exist_ok=True)
            shared_file_path = os.path.join(user_shared_dir, safe_file_name)
            
            try:
                shutil.copy2(private_file_path, shared_file_path)
                self._send_response(self.config['RESPONSES']['USER_SHARED_SUCCESS'])
                logging.info(f"[{self.address}] User '{self.username}' made private file '{safe_file_name}' shared.")
            except Exception as e:
                logging.error(f"[{self.address}] Error copying file: {e}", exc_info=True)
                self._send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}{str(e)}")
        else:
            logging.warning(f"[{self.address}] User '{self.username}' tried to make a non-existent file shared: '{safe_file_name}'.")
            self._send_response(self.config['RESPONSES']['FILE_NOT_FOUND'])     