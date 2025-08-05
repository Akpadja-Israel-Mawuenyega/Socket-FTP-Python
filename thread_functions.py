import threading
import socket
import tqdm
import shutil
import os
import sys
import logging
import ssl
from server_auth import ServerAuthHandler
from concurrent.futures import ThreadPoolExecutor
from user_management import DatabaseManager

class ClientHandler(threading.Thread):
    def __init__(self, client_socket: socket.socket, address: tuple, server_config: dict, auth_handler: ServerAuthHandler, db_manager: DatabaseManager):
        threading.Thread.__init__(self)
        self.client_socket = client_socket
        self.address = address
        self.config = server_config
        self.auth_handler = auth_handler
        self.db_manager= db_manager
        self.upload_dir = self.config['SERVER']['UPLOAD_DIR']
        self.public_files_dir = self.config['SERVER']['PUBLIC_FILES_DIR']
        self.shared_uploads_dir = self.config['SERVER']['SHARED_UPLOADS_DIR']
        self.buffer_size = self.config['SERVER'].getint('BUFFER_SIZE')
        self.separator = self.config['SERVER']['SEPARATOR']
        self.session_id = None
        self.username = None
        self.user_role = None
        self.user_id = None
        self.executor = ThreadPoolExecutor(max_workers=5)
        logging.info(f"[{self.address}] Client handler initialized.")

    def run(self):
        try:
            self.handle_client_connection()
        except (socket.error, ConnectionResetError) as e:
            logging.warning(f"[{self.address}] Connection lost: {e}")
        finally:
            self.cleanup()

    def handle_client_connection(self):
        logging.info(f"[{self.address}] Waiting for commands.")
        while True:
            try:
                command_raw = self.client_socket.recv(self.buffer_size)
                if not command_raw:
                    break
                
                command_str = command_raw.decode('utf-8').strip()
                if not command_str:
                    continue
                                
                parts = command_str.split(self.separator)
                command = parts[0]
                
                if command in [self.config['COMMANDS']['LOGIN'], self.config['COMMANDS']['REGISTER']]:
                    if len(parts) >= 2:
                        username = parts[1]
                        logging.info(f"[{self.address}] Received command '{command}' from user '{username}'. Password masked.")
                    else:
                        logging.warning(f"[{self.address}] Received malformed command: '{command_str}'")
                else:
                    logging.info(f"[{self.address}] Received raw command: '{command_str}'")
                
                # --- Authentication Commands ---
                if command == self.auth_handler.REGISTER_COMMAND:
                    if len(parts) >= 3:
                        username = parts[1]
                        password = parts[2]
                        response = self.auth_handler.register_user(username, password)
                        self.send_response(response)
                    else:
                        self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Invalid REGISTER command format.")
                
                elif command == self.auth_handler.LOGIN_COMMAND:
                    if len(parts) >= 3:
                        username = parts[1]
                        password = parts[2]
                        response = self.auth_handler.login_user(username, password)
                        self.send_response(response)
                        if response.startswith(self.auth_handler.LOGIN_SUCCESS_RESPONSE):
                            _response, self.session_id, self.username, self.user_role = response.split(self.separator)
                            self.user_id = self.db_manager.get_user_id_by_username(self.username)
                            user_dir = os.path.join(self.upload_dir, self.username)
                            os.makedirs(user_dir, exist_ok=True)
                    else:
                        self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Invalid LOGIN command format.")
                
                elif command == self.auth_handler.LOGOUT_COMMAND:
                    if len(parts) >= 2 and parts[1] == self.session_id:
                        response = self.auth_handler.logout_user(self.session_id)
                        self.send_response(response)
                        self.session_id = None
                        self.username = None
                        self.user_role = None
                        self.user_id =  None
                    else:
                        self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Invalid session or command format.")
                
                elif command == self.config['COMMANDS']['QUIT']:
                    logging.info(f"[{self.address}] Client requested to quit.")
                    self.auth_handler.logout_user(self.session_id)
                    break

                # --- File Transfer Commands ---
                elif command == self.config['COMMANDS']['UPLOAD_PRIVATE']:
                    if len(parts) >= 4 and self.auth_handler.is_valid_session(parts[1]):
                        file_name = parts[2]
                        file_size_str = parts[3]
                        self.handle_upload_file(file_name, file_size_str, private=True, public=False)
                    else:
                        self.send_response(self.auth_handler.INVALID_SESSION_RESPONSE)
                         
                elif command == self.config['COMMANDS']['UPLOAD_PUBLIC']:
                    if len(parts) >= 4 and self.auth_handler.is_valid_session(parts[1]):
                        file_name = parts[2]
                        file_size_str = parts[3]
                        self.handle_upload_file(file_name, file_size_str, private=False, public=True)
                    else:
                        self.send_response(self.auth_handler.INVALID_SESSION_RESPONSE)

                elif command == self.config['COMMANDS']['UPLOAD_FOR_SHARING']:
                    if len(parts) >= 5 and self.auth_handler.is_valid_session(parts[2]):
                        file_name = parts[3]
                        file_size_str = parts[4]
                        recipient_username = parts[1]
                        self.handle_upload_file(file_name, file_size_str, recipient_username, private=False, public=False)
                    else:
                        self.send_response(self.auth_handler.INVALID_SESSION_RESPONSE)

                elif command == self.config['COMMANDS']['DOWNLOAD_PRIVATE']:
                    if len(parts) >= 3 and self.auth_handler.is_valid_session(parts[1]):
                        file_name = parts[2]
                        self.handle_download_file(file_name, from_private=True, from_public=False)
                    else:
                        self.send_response(self.auth_handler.INVALID_SESSION_RESPONSE)

                elif command == self.config['COMMANDS']['LIST_PRIVATE']:
                    if len(parts) >= 2 and self.auth_handler.is_valid_session(parts[1]):
                        self.handle_list_private()
                    else:
                        self.send_response(self.auth_handler.INVALID_SESSION_RESPONSE)
                
                elif command == self.config['COMMANDS']['LIST_PUBLIC']:
                    if len(parts) >= 2 and self.auth_handler.is_valid_session(parts[1]):
                        self.handle_list_public_files()
                    else:
                        self.send_response(self.auth_handler.INVALID_SESSION_RESPONSE)        

                elif command == self.config['COMMANDS']['DOWNLOAD_SERVER_PUBLIC']:
                    if len(parts) >= 2:
                        file_name = parts[1]
                        self.handle_download_file(file_name, from_public=True, from_private=False)
                    else:
                        self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Invalid DOWNLOAD_SERVER_PUBLIC command format.")

                elif command == self.config['COMMANDS']['DOWNLOAD_SHARED']:
                    if len(parts) >= 3 and self.auth_handler.is_valid_session(parts[1]):
                        owner_and_file_name = parts[2]
                        self.handle_download_file(owner_and_file_name, from_public=False, from_private=False)
                    else:
                        self.send_response(self.auth_handler.INVALID_SESSION_RESPONSE)

                elif command == self.config['COMMANDS']['LIST_SHARED']:
                    if len(parts) >= 2 and self.auth_handler.is_valid_session(parts[1]):
                        self.list_shared_files()
                    else:
                        self.send_response(self.auth_handler.INVALID_SESSION_RESPONSE)
                
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
                            self.send_response(self.auth_handler.PERMISSION_DENIED_RESPONSE)
                    else:
                        self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Invalid MAKE_PUBLIC_ADMIN command format.")
                
                elif command == self.config['COMMANDS']['MAKE_PUBLIC_USER']:
                    if len(parts) >= 3 and self.auth_handler.is_valid_session(parts[1]):
                        file_name = parts[2]
                        if self.user_role in ['user', 'admin']:
                            self.make_public_user(file_name)
                        else:
                            self.send_response(self.auth_handler.PERMISSION_DENIED_RESPONSE)
                    else:
                        self.send_response(self.auth_handler.INVALID_SESSION_RESPONSE)
                         
                elif command == self.config['COMMANDS']['MAKE_SHARED_USER']:
                    if len(parts) >= 4 and self.auth_handler.is_valid_session(parts[1]):
                        file_name = parts[2]
                        recipient_username = parts[3]
                        if self.user_role in ['user', 'admin']:
                            self.make_shared_user(file_name, recipient_username)
                        else:
                            self.send_response(self.auth_handler.PERMISSION_DENIED_RESPONSE)
                    else:
                        self.send_response(self.auth_handler.INVALID_SESSION_RESPONSE)
                
                elif command == self.config['COMMANDS']['ADMIN_DELETE_FILE']:
                        if len(parts) < 3:
                            self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Invalid command format. Usage: ADMIN_DELETE_FILE <session_id> <file_id>")
                            continue
                        
                        file_name = parts[2]
                        self.admin_delete_public_file(self.session_id, file_name)
              
            except IndexError:
                logging.error(f"[{self.address}] Malformed command received: {command_str}")
                self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Malformed command.")
            except (socket.error, ConnectionResetError) as e:
                logging.warning(f"[{self.address}] Connection lost: {e}")
                break
            except Exception as e:
                logging.error(f"[{self.address}] An unexpected error occurred: {e}", exc_info=True)
                self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}An internal server error occurred.")

    def send_response(self, response):
        try:
            self.client_socket.sendall(response.encode('utf-8'))
        except (socket.error, ConnectionResetError) as e:
            logging.warning(f"[{self.address}] Failed to send response: {e}")

    def cleanup(self):
        if self.client_socket:
            self.client_socket.close()
        logging.info(f"[{self.address}] Disconnected.")

    def handle_upload_file(self, file_name, file_size_str, recipient_username=None, private=False, public=False):
        file_path = None        
        try:
            file_size = int(file_size_str)
            
            safe_file_name = os.path.basename(file_name)
            
            is_public_db_flag = False
            user_id_for_db = self.user_id 
            recipient_id_for_db = None

            if private:
                base_dir = os.path.join(self.upload_dir, self.username)
            elif public:
                base_dir = self.public_files_dir
                is_public_db_flag = True
            else: 
                if not recipient_username:
                    logging.error(f"[{self.address}] No recipient specified for shared upload.")
                    self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Recipient username is required for sharing.")
                    return
                
                user_record = self.db_manager.get_user_by_username(recipient_username)
                if user_record:
                    recipient_id_for_db = user_record['id']
                    base_dir = os.path.join(self.shared_uploads_dir, recipient_username)
                else:
                    logging.error(f"[{self.address}] User not found: '{recipient_username}'.")
                    self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}User not found.")
                    return
            
            os.makedirs(base_dir, exist_ok=True)
            
            file_path = os.path.join(base_dir, safe_file_name)
            resolved_path = os.path.abspath(file_path)

            if not resolved_path.startswith(os.path.abspath(base_dir)):
                logging.error(f"[{self.address}] Path traversal attempt detected during upload: {file_name}")
                self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Invalid file path.")
                return
            
            logging.info(f"[{self.address}] Saving uploaded file to: {resolved_path}")
            
            if not self.db_manager.add_file_record(user_id_for_db, safe_file_name, file_size, is_public_db_flag, recipient_id=recipient_id_for_db):
                logging.error(f"[{self.address}] Failed to add file record to database for user {user_id_for_db}.")
                self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Failed to upload file.")
                return

            self.send_response(self.config['RESPONSES']['READY_FOR_DATA'])

            with open(resolved_path, "wb") as f:
                with tqdm.tqdm(total=file_size, unit="B", unit_scale=True, unit_divisor=1024, desc=f"Receiving {file_name}") as progress:
                    bytes_received = 0
                    while bytes_received < file_size:
                        bytes_to_read = min(self.buffer_size, file_size - bytes_received)
                        bytes_read = self.client_socket.recv(bytes_to_read)
                        if not bytes_read:
                            logging.warning(f"[{self.address}] Client disconnected during file upload of {file_name}.")
                            break 
                        f.write(bytes_read)
                        bytes_received += len(bytes_read)
                        progress.update(len(bytes_read))
            
            if bytes_received == file_size:
                logging.info(f"[{self.address}] File '{file_name}' uploaded successfully to {resolved_path}.")
                self.send_response(self.config['RESPONSES']['UPLOAD_SUCCESS'])
            else:
                logging.error(f"[{self.address}] Incomplete upload of '{file_name}'. Expected {file_size} bytes, got {bytes_received}.")
                if os.path.exists(resolved_path):
                    os.remove(resolved_path) 
                self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Incomplete file upload.")

        except (ValueError, IndexError) as e:
            logging.error(f"[{self.address}] Invalid file size or command format: {e}")
            self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Invalid command format.")
        except Exception as e:
            logging.error(f"[{self.address}] An unexpected error occurred during file upload: {e}", exc_info=True)
            self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Error during file upload.")
            if file_path and os.path.exists(file_path):
                os.remove(file_path)


    def handle_download_file(self, file_identifier, from_private=False, from_public=False):
        file_path = None
        base_dir = None
        file_record = None

        try:
            if from_private:
                safe_file_name = os.path.basename(file_identifier)
                file_record = self.db_manager.get_private_file_record(file_name=safe_file_name, owner_id=self.user_id)
                if not file_record:
                    self.send_response(self.config['RESPONSES']['FILE_NOT_FOUND'])
                    logging.warning(f"[{self.address}] Private file '{safe_file_name}' not found or not owned by user '{self.username}'.")
                    return
                base_dir = os.path.join(self.upload_dir, self.username)

            elif from_public:
                safe_file_name = os.path.basename(file_identifier)
                file_record = self.db_manager.get_public_file_record(file_name=safe_file_name)
                if not file_record:
                    self.send_response(self.config['RESPONSES']['FILE_NOT_FOUND'])
                    logging.warning(f"[{self.address}] Public file '{safe_file_name}' not found.")
                    return
                base_dir = self.public_files_dir

            else:
                safe_file_name = os.path.basename(file_identifier)
                file_record = self.db_manager.get_file_record_in_shared_folder(file_name=safe_file_name, recipient_id=self.user_id)
                if not file_record:
                    self.send_response(self.config['RESPONSES']['FILE_NOT_FOUND'])
                    logging.warning(f"[{self.address}] Shared file '{safe_file_name}' not found for user '{self.username}'.")
                    return
                
                base_dir = os.path.join(self.shared_uploads_dir, self.username)

            file_path = os.path.join(base_dir, os.path.basename(file_record['file_name']))
            resolved_path = os.path.abspath(file_path)

            if not resolved_path.startswith(os.path.abspath(base_dir)):
                self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Invalid file path.")
                logging.error(f"[{self.address}] Path traversal attempt detected during download: {file_identifier}")
                return

            if not os.path.isfile(resolved_path):
                self.send_response(self.config['RESPONSES']['FILE_NOT_FOUND'])
                logging.warning(f"[{self.address}] File '{resolved_path}' not found on disk for download.")
                return

            logging.info(f"[{self.address}] Attempting to download file from: {resolved_path}")
            
            file_size = os.path.getsize(file_path)
            self.send_response(f"{self.config['RESPONSES']['DOWNLOAD_READY']}{self.separator}{file_record['file_name']}{self.separator}{file_size}")

            with open(resolved_path, "rb") as f:
                with tqdm.tqdm(total=file_size, unit="B", unit_scale=True, unit_divisor=1024, desc=f"Sending {file_record['file_name']}") as progress:
                    while True:
                        bytes_read = f.read(self.buffer_size)
                        if not bytes_read:
                            break
                        self.client_socket.sendall(bytes_read)
                        progress.update(len(bytes_read))
                
            logging.info(f"[{self.address}] File '{file_record['file_name']}' sent successfully.")
            self.send_response(self.config['RESPONSES']['DOWNLOAD_COMPLETE'])
            
        except (ValueError, KeyError) as e:
            logging.error(f"[{self.address}] Invalid file identifier or database record format: {e}", exc_info=True)
            self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Invalid command format or file record.")
        except Exception as e:
            logging.error(f"[{self.address}] Error during file download: {e}", exc_info=True)
            self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Error during file download.")

    def handle_list_public_files(self): 
        try:
            public_files = self.db_manager.get_public_files()
            
            if public_files:
                file_info_strings = [f"{f['file_id']},{f['file_name']}" for f in public_files]
                
                response_data = self.separator.join(file_info_strings)

                response = f"{self.config['RESPONSES']['LIST_SUCCESS']}{self.separator}{response_data}"
                self.send_response(response)
            else:
                self.send_response(self.config['RESPONSES']['NO_FILES_PUBLIC'])
            logging.info(f"[{self.address}] Listed public files for user '{self.username}'.")
        except Exception as e:
            logging.error(f"[{self.address}] Error listing public files: {e}", exc_info=True)
            self.send_response(self.config['RESPONSES']['LIST_FAILED'])       

    def handle_list_private(self):
        try:
            private_files = self.db_manager.get_files(owner_id=self.user_id, is_public=False)
            
            if private_files:
                file_names = [f['file_name'] for f in private_files]
                response = f"{self.config['RESPONSES']['PRIVATE_LIST']}{self.separator}{self.separator.join(file_names)}"
                self.send_response(response)
            else:
                self.send_response(self.config['RESPONSES']['NO_FILES_PRIVATE'])
            logging.info(f"[{self.address}] Listed private files for user '{self.username}'.")
        except Exception as e:
            logging.error(f"[{self.address}] Error listing private files: {e}", exc_info=True)
            self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}{str(e)}")

    def list_shared_files(self):
        try:
            all_public_files = self.db_manager.get_files(is_public=True)

            if all_public_files:
                formatted_files = []
                for file_record in all_public_files:
                    owner_record = self.db_manager.get_user_by_id(file_record['owner_id'])
                    owner_username = owner_record['username'] if owner_record else 'public'
                    
                    if file_record['owner_id'] != 0:
                        formatted_files.append(f"{owner_username}/{file_record['file_name']}")
                
                if formatted_files:
                    response = f"{self.config['RESPONSES']['SHARED_LIST']}{self.separator}{self.separator.join(formatted_files)}"
                    self.send_response(response)
                else:
                    self.send_response(self.config['RESPONSES']['NO_FILES_SHARED'])
            else:
                self.send_response(self.config['RESPONSES']['NO_FILES_SHARED'])
            logging.info(f"[{self.address}] Listed shared files.")
        except Exception as e:
            logging.error(f"[{self.address}] Error listing shared files: {e}", exc_info=True)
            self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}{str(e)}")


    def make_public_admin(self, owner_username, file_name):
        try:
            safe_owner_username = os.path.basename(owner_username)
            safe_file_name = os.path.basename(file_name)

            owner_id = self.db_manager.get_user_id_by_username(safe_owner_username)
            if not owner_id:
                self.send_response(self.config['RESPONSES']['FILE_NOT_FOUND'])
                return

            file_record = self.db_manager.get_file_record(file_name=safe_file_name, owner_id=owner_id)
            if not file_record:
                self.send_response(self.config['RESPONSES']['FILE_NOT_FOUND'])
                return
            
            private_file_path = os.path.join(self.upload_dir, safe_owner_username, safe_file_name)
            shared_file_path = os.path.join(self.shared_uploads_dir, safe_owner_username, safe_file_name)
            public_file_path = os.path.join(self.public_files_dir, safe_file_name)

            source_file_path = None
            if os.path.isfile(private_file_path):
                source_file_path = private_file_path
            elif os.path.isfile(shared_file_path):
                source_file_path = shared_file_path

            if source_file_path:
                shutil.copy2(source_file_path, public_file_path)
                self.db_manager.update_file_visibility(file_record['file_id'], new_is_public=True)
                self.send_response(self.config['RESPONSES']['ADMIN_PUBLIC_SUCCESS'])
                logging.info(f"[{self.address}] Admin copied '{safe_file_name}' from '{safe_owner_username}' to public.")
            else:
                logging.warning(f"[{self.address}] Admin tried to make a non-existent file '{safe_file_name}' from '{safe_owner_username}' public.")
                self.send_response(self.config['RESPONSES']['FILE_NOT_FOUND'])
        except Exception as e:
            logging.error(f"[{self.address}] Error making file public by admin: {e}", exc_info=True)
            self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}{str(e)}")

    def make_public_user(self, file_name):
        try:
            safe_file_name = os.path.basename(file_name)
            
            file_record = self.db_manager.get_private_file_record(file_name=safe_file_name, owner_id=self.user_id)
            if not file_record:
                logging.warning(f"[{self.address}] User '{self.username}' tried to make a non-existent file public: '{safe_file_name}'.")
                self.send_response(self.config['RESPONSES']['FILE_NOT_FOUND'])
                return

            private_file_path = os.path.join(self.upload_dir, self.username, safe_file_name)
            public_file_path = os.path.join(self.public_files_dir, safe_file_name)
            
            if os.path.isfile(private_file_path):
                shutil.copy2(private_file_path, public_file_path)
                self.db_manager.update_file_visibility(file_record['file_id'], new_is_public=True)
                self.send_response(self.config['RESPONSES']['USER_PUBLIC_SUCCESS'])
                logging.info(f"[{self.address}] User '{self.username}' made file '{safe_file_name}' public.")
            else:
                logging.warning(f"[{self.address}] File '{safe_file_name}' exists in DB but not on disk for user '{self.username}'.")
                self.send_response(self.config['RESPONSES']['FILE_NOT_FOUND'])
        except Exception as e:
            logging.error(f"[{self.address}] Error making file public by user: {e}", exc_info=True)
            self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}{str(e)}")
            
    def make_shared_user(self, file_name, recipient_username):
        try:
            safe_file_name = os.path.basename(file_name)
            
            logging.info(f"DEBUG: owner_id being used: {self.user_id}")
            logging.info(f"DEBUG: safe_file_name being used: '{safe_file_name}'")
            
            file_record = self.db_manager.get_private_file_record(file_name=safe_file_name, owner_id=self.user_id)
            if not file_record:
                self.send_response(self.config['RESPONSES']['FILE_NOT_FOUND'])
                return

            recipient_record = self.db_manager.get_user_by_username(recipient_username)
            if not recipient_record:
                self.send_response(self.config['RESPONSES']['USER_NOT_FOUND'])
                return
            
            private_file_path = os.path.join(self.upload_dir, self.username, safe_file_name)
            if not os.path.isfile(private_file_path):
                self.send_response(self.config['RESPONSES']['FILE_NOT_FOUND'])
                return

            recipient_shared_dir = os.path.join(self.shared_uploads_dir, recipient_username)
            os.makedirs(recipient_shared_dir, exist_ok=True)
            shared_file_path = os.path.join(recipient_shared_dir, safe_file_name)
            
            shutil.copy2(private_file_path, shared_file_path)

            self.db_manager.add_file_record(
                owner_id=self.user_id,
                file_name=safe_file_name,
                file_size=file_record['file_size'],
                is_public=False,
                recipient_id=recipient_record['id']
            )

            self.send_response(self.config['RESPONSES']['USER_SHARED_SUCCESS'])
        
        except Exception:
            self.send_response(f"{self.auth_handler.ERROR_RESPONSE}{self.separator}Error sharing file.")
    
    def admin_delete_public_file(self, session_id, file_id):
        session_data = self.auth_handler.get_session_data(session_id)
        user_id = session_data['user_id']
        user_role = session_data['role']

        if user_role != 'admin':
            self.send_response(self.auth_handler.PERMISSION_DENIED_RESPONSE)
            logging.warning(f"[{self.address}] Non-admin user '{self.username}' attempted to use ADMIN_DELETE_FILE.")
            return

        file_name, _, is_public = self.db_manager.delete_file(file_id, user_id, user_role)
        
        if file_name and is_public:
            try:
                file_path = os.path.join(self.config['SERVER']['PUBLIC_FILES_DIR'], file_name)
                
                if os.path.exists(file_path):
                    os.remove(file_path)
                    self.send_response(f"{self.config['RESPONSES']['ADMIN_DELETE_SUCCESS']}{self.separator}File '{file_name}' and record deleted.")
                    logging.info(f"[{self.address}] Admin '{self.username}' successfully deleted file '{file_name}'.")
                else:
                    self.send_response(f"{self.config['RESPONSES']['ADMIN_DELETE_SUCCESS']}{self.separator}Record for '{file_name}' deleted, but file not found on disk.")
                    logging.warning(f"[{self.address}] Admin '{self.username}' deleted record for file '{file_name}', but physical file was not found.")

            except Exception as e:
                logging.error(f"Failed to delete physical file '{file_name}': {e}")
                self.send_response(f"{self.config['RESPONSES']['ADMIN_DELETE_FAILED']}{self.separator}Failed to delete file '{file_name}' on disk.")
        else:
            self.send_response(f"{self.config['RESPONSES']['ADMIN_DELETE_FAILED']}{self.separator}Failed to delete file ID '{file_id}'. It may not exist or may not be public.")
        