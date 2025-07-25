import threading
import socket
import tqdm
import os
import sys
import logging
from server_auth import ServerAuthHandler
import json
import base64

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
                
                logging.debug(f"[{self.address}] Received raw command: '{command_str}'")
                
                parts = command_str.split(self.separator)
                command = parts[0]
                
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

                elif command == self.config['COMMANDS']['UPLOAD_PRIVATE']:
                    if len(parts) >= 4 and self.auth_handler.is_valid_session(parts[1]):
                        self.handle_upload(parts[2], parts[3], private=True)
                    else:
                        self._send_response(self.auth_handler.INVALID_SESSION_RESPONSE)

                elif command == self.config['COMMANDS']['UPLOAD_FOR_SHARING']:
                    if len(parts) >= 4 and self.auth_handler.is_valid_session(parts[1]):
                        self.handle_upload(parts[2], parts[3], private=False)
                    else:
                        self._send_response(self.auth_handler.INVALID_SESSION_RESPONSE)

                elif command == self.config['COMMANDS']['DOWNLOAD_SERVER_PUBLIC']:
                    if len(parts) >= 2:
                        self.handle_download_public(parts[1])
                    else:
                        self._send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Invalid DOWNLOAD_SERVER_PUBLIC command format.")

                elif command == self.config['COMMANDS']['DOWNLOAD_SHARED']:
                    if len(parts) >= 3 and self.auth_handler.is_valid_session(parts[1]):
                        self.handle_download_shared(parts[2])
                    else:
                        self._send_response(self.auth_handler.INVALID_SESSION_RESPONSE)

                elif command == self.config['COMMANDS']['LIST_SHARED']:
                    if len(parts) >= 2 and self.auth_handler.is_valid_session(parts[1]):
                        self.list_shared_files()
                    else:
                        self._send_response(self.auth_handler.INVALID_SESSION_RESPONSE)
                
                elif command == self.config['COMMANDS']['MAKE_PUBLIC_ADMIN']:
                    if len(parts) >= 3 and self.auth_handler.is_valid_session(parts[1]):
                        if self.auth_handler.get_user_role(self.auth_handler.get_username_from_session(parts[1])) == 'admin':
                            self.make_public_admin(parts[2])
                        else:
                            self._send_response(self.auth_handler.PERMISSION_DENIED_RESPONSE)
                    else:
                        self._send_response(self.auth_handler.INVALID_SESSION_RESPONSE)
                
                else:
                    self._send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Unknown command.")
                    
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

    def handle_upload(self, file_name, file_size_str, private):
        try:
            file_size = int(file_size_str)
            target_dir = self.upload_dir if private else self.shared_uploads_dir
            os.makedirs(target_dir, exist_ok=True)
            file_path = os.path.join(target_dir, file_name)
            
            self._send_response(self.config['RESPONSES']['READY_FOR_DATA'])
            
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
            
            self._send_response(self.config['RESPONSES']['UPLOAD_DONE'])
            logging.info(f"[{self.address}] File '{file_name}' uploaded successfully to {target_dir}.")
        except Exception as e:
            logging.error(f"[{self.address}] Error during file upload: {e}", exc_info=True)
            self._send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}{str(e)}")

    def handle_download_public(self, file_name):
        file_path = os.path.join(self.public_files_dir, file_name)
        if os.path.isfile(file_path):
            file_size = os.path.getsize(file_path)
            response = f"{self.config['RESPONSES']['DOWNLOAD_READY']}{self.separator}{file_size}"
            self._send_response(response)
            
            with open(file_path, "rb") as f:
                with tqdm.tqdm(total=file_size, unit="B", unit_scale=True, unit_divisor=1024, desc=f"Sending {file_name}") as progress:
                    while True:
                        bytes_read = f.read(self.buffer_size)
                        if not bytes_read:
                            break
                        self.client_socket.sendall(bytes_read)
                        progress.update(len(bytes_read))
            self._send_response(self.config['RESPONSES']['DOWNLOAD_COMPLETE'])
            logging.info(f"[{self.address}] File '{file_name}' sent successfully.")
        else:
            self._send_response(self.config['RESPONSES']['FILE_NOT_FOUND'])
            logging.warning(f"[{self.address}] Public file '{file_name}' not found.")

    def handle_download_shared(self, file_name):
        file_path = os.path.join(self.shared_uploads_dir, file_name)
        if os.path.isfile(file_path):
            file_size = os.path.getsize(file_path)
            response = f"{self.config['RESPONSES']['DOWNLOAD_READY']}{self.separator}{file_size}"
            self._send_response(response)
            
            with open(file_path, "rb") as f:
                with tqdm.tqdm(total=file_size, unit="B", unit_scale=True, unit_divisor=1024, desc=f"Sending {file_name}") as progress:
                    while True:
                        bytes_read = f.read(self.buffer_size)
                        if not bytes_read:
                            break
                        self.client_socket.sendall(bytes_read)
                        progress.update(len(bytes_read))
            self._send_response(self.config['RESPONSES']['DOWNLOAD_COMPLETE'])
            logging.info(f"[{self.address}] File '{file_name}' sent successfully.")
        else:
            self._send_response(self.config['RESPONSES']['FILE_NOT_FOUND'])
            logging.warning(f"[{self.address}] Shared file '{file_name}' not found.")

    def list_shared_files(self):
        try:
            shared_files = os.listdir(self.shared_uploads_dir)
            if shared_files:
                response = f"{self.config['RESPONSES']['SHARED_LIST']}{self.separator}{self.separator.join(shared_files)}"
                self._send_response(response)
            else:
                self._send_response(self.config['RESPONSES']['NO_FILES_SHARED'])
            logging.info(f"[{self.address}] Listed shared files.")
        except FileNotFoundError:
            self._send_response(self.config['RESPONSES']['NO_FILES_SHARED'])
            logging.warning(f"[{self.address}] Shared directory not found. No files to list.")
        except Exception as e:
            logging.error(f"[{self.address}] Error listing shared files: {e}", exc_info=True)
            self._send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}{str(e)}")

    def make_public_admin(self, file_name):
        # Admin can make a file public from either shared or their private folder
        shared_file_path = os.path.join(self.shared_uploads_dir, file_name)
        private_file_path = os.path.join(self.upload_dir, file_name)
        source_file_path = None
        if os.path.isfile(shared_file_path):
            source_file_path = shared_file_path
            logging.debug(f"[{self.address}] Found file in shared folder: {source_file_path}")
        elif os.path.isfile(private_file_path):
            source_file_path = private_file_path
            logging.debug(f"[{self.address}] Found file in admin's private folder: {source_file_path}")

        if source_file_path:
            public_file_path = os.path.join(self.public_files_dir, file_name)
            try:
                os.rename(source_file_path, public_file_path)
                self._send_response(self.config['RESPONSES']['ADMIN_PUBLIC_SUCCESS'])
                logging.info(f"[{self.address}] Admin moved '{file_name}' to public.")
            except Exception as e:
                logging.error(f"[{self.address}] Error moving file: {e}", exc_info=True)
                self._send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}{str(e)}")
        else:
            logging.warning(f"[{self.address}] Admin tried to make a non-existent file public: '{file_name}'. Checked paths: {shared_file_path} and {private_file_path}")
            self._send_response(self.config['RESPONSES']['FILE_NOT_FOUND'])