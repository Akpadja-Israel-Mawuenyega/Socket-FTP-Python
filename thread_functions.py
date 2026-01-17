import threading
import socket
import shutil
import os
import logging
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
        self.db_manager = db_manager
        self.upload_dir = self.config['SERVER']['UPLOAD_DIR']
        self.public_files_dir = self.config['SERVER']['PUBLIC_FILES_DIR']
        self.shared_uploads_dir = self.config['SERVER']['SHARED_UPLOADS_DIR']
        self.buffer_size = self.config['SERVER'].getint('BUFFER_SIZE')
        self.separator = self.config['SERVER']['SEPARATOR']
        
        # User Session State
        self.session_id = None
        self.username = None
        self.user_role = None
        self.user_id = None
        
        logging.info(f"[{self.address}] Client handler initialized.")

    def run(self):
        try:
            self.handle_client_connection()
        except (socket.error, ConnectionResetError):
            logging.warning(f"[{self.address}] Connection lost.")
        finally:
            self.cleanup()

    def handle_client_connection(self):
        while True:
            try:
                data = self.client_socket.recv(self.buffer_size).decode('utf-8').strip()
                if not data: break
                
                parts = data.split(self.separator)
                command = parts[0]

                # --- Session-less Commands (Login / Register) ---
                if command == self.auth_handler.REGISTER_COMMAND:
                    self.send_response(self.auth_handler.register_user(parts[1], parts[2]))
                    continue
                
                if command == self.auth_handler.LOGIN_COMMAND:
                    response = self.auth_handler.login_user(parts[1], parts[2])
                    if response.startswith(self.auth_handler.LOGIN_SUCCESS_RESPONSE):
                        # Assuming Auth returns: SUCCESS|SID|USER|ROLE|ID
                        _, self.session_id, self.username, self.user_role, self.user_id = response.split(self.separator)
                        os.makedirs(os.path.join(self.upload_dir, self.username), exist_ok=True)
                    self.send_response(response)
                    continue

                # --- Authenticated Generic Commands ---
                if not self.auth_handler.is_valid_session(parts[1]):
                    self.send_response(self.auth_handler.INVALID_SESSION_RESPONSE)
                    continue

                # 1. LISTING (Generic)
                if command in [self.config['COMMANDS']['LIST_PRIVATE'], self.config['COMMANDS']['LIST_PUBLIC'], self.config['COMMANDS']['LIST_SHARED']]:
                    self.handle_file_list(command)

                # 2. DOWNLOAD (Generic)
                elif command in [self.config['COMMANDS']['DOWNLOAD_PRIVATE'], self.config['COMMANDS']['DOWNLOAD_SHARED'], self.config['COMMANDS']['DOWNLOAD_SERVER_PUBLIC']]:
                    self.handle_file_download(parts[2])

                # 3. UPLOAD (Generic)
                elif command in [self.config['COMMANDS']['UPLOAD_PRIVATE'], self.config['COMMANDS']['UPLOAD_PUBLIC'], self.config['COMMANDS']['UPLOAD_FOR_SHARING']]:
                    recipient = parts[2] if command == self.config['COMMANDS']['UPLOAD_FOR_SHARING'] else None
                    # Metadata for upload follows the command and session parts
                    self.handle_file_upload(command, parts, recipient)

                # 4. DELETE (Generic with Admin Override)
                elif command in ['DELETE_FILE', self.config['COMMANDS']['ADMIN_DELETE_FILE']]:
                    is_admin_req = (command == self.config['COMMANDS']['ADMIN_DELETE_FILE'])
                    self.handle_file_delete(parts[2], is_admin_req)

                # 5. SHARE / VISIBILITY (Generic)
                elif command in [self.config['COMMANDS']['MAKE_PUBLIC_USER'], self.config['COMMANDS']['MAKE_SHARED_USER']]:
                    target = parts[3] if len(parts) > 3 else None
                    self.handle_file_status_change(parts[2], command, target)

                elif command == self.config['COMMANDS']['LOGOUT']:
                    self.auth_handler.logout_user(self.session_id)
                    break

            except Exception as e:
                logging.error(f"Command Error: {e}", exc_info=True)
                self.send_response("ERROR|Internal server error.")

    # --- GENERIC IMPLEMENTATIONS ---

    def handle_file_list(self, cmd):
        """Uses refactored db_manager.get_files with optional filters."""
        if cmd == self.config['COMMANDS']['LIST_PUBLIC']:
            files = self.db_manager.get_files(is_public=True)
        elif cmd == self.config['COMMANDS']['LIST_SHARED']:
            files = self.db_manager.get_files(recipient_id=self.user_id, is_public=False)
        else:
            files = self.db_manager.get_files(owner_id=self.user_id, is_public=False)

        if not files:
            self.send_response("LIST_EMPTY")
        else:
            file_data = "|".join([f"{f['file_id']}:{f['file_name']}" for f in files])
            self.send_response(f"LIST_SUCCESS{self.separator}{file_data}")

    def handle_file_upload(self, cmd, parts, recipient_username=None):
        """Unified Upload Logic: Streams data then calls add_file_record."""
        try:
            file_name = parts[-2]
            file_size = int(parts[-1])
            
            is_public = (cmd == self.config['COMMANDS']['UPLOAD_PUBLIC'])
            recipient_id = None
            if recipient_username:
                recip_record = self.db_manager.get_user_record(username=recipient_username)
                recipient_id = recip_record['id'] if recip_record else None

            # Resolve destination using generic path logic
            temp_record = {'file_name': file_name, 'is_public': is_public, 'recipient_id': recipient_id}
            dest_path = self.resolve_path(temp_record)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            self.send_response("READY_TO_RECEIVE")
            
            with open(dest_path, "wb") as f:
                received = 0
                while received < file_size:
                    chunk = self.client_socket.recv(min(self.buffer_size, file_size - received))
                    if not chunk: break
                    f.write(chunk)
                    received += len(chunk)

            if received == file_size:
                self.db_manager.add_file_record(self.user_id, file_name, file_size, is_public, recipient_id)
                self.send_response("UPLOAD_SUCCESS")
            else:
                if os.path.exists(dest_path): os.remove(dest_path)
                self.send_response("UPLOAD_FAILED|Incomplete transfer.")
        except Exception as e:
            self.send_response(f"UPLOAD_ERROR|{str(e)}")

    def handle_file_download(self, file_id):
        """Uses refactored db_manager.get_file_record and checks permissions."""
        
        f = self.db_manager.get_file_record(file_id=file_id)
        if not f:
            return self.send_response("FILE_NOT_FOUND")

        # Permission logic: Admin OR Owner OR Recipient OR Public
        can_access = (f['is_public'] or f['owner_id'] == self.user_id or 
                      f['recipient_id'] == self.user_id or self.user_role == 'admin')

        if not can_access:
            return self.send_response("ACCESS_DENIED")

        path = self.resolve_path(f)
        if os.path.exists(path):
            self.send_response(f"DOWNLOAD_START{self.separator}{f['file_name']}{self.separator}{f['file_size']}")
            with open(path, "rb") as src:
                self.client_socket.sendfile(src)
        else:
            self.send_response("FILE_REMOVED_FROM_DISK")

    def handle_file_delete(self, file_id, is_admin_req):
        """Uses refactored db_manager.delete_file_record with optional owner_id."""
        owner_filter = None if (is_admin_req and self.user_role == 'admin') else self.user_id
        
        # We need the record first to know the path for physical removal
        f = self.db_manager.get_file_record(file_id=file_id)
        
        if f and self.db_manager.delete_file_record(file_id, owner_id=owner_filter):
            path = self.resolve_path(f)
            if os.path.exists(path):
                os.remove(path)
            self.send_response("DELETE_SUCCESS")
        else:
            self.send_response("DELETE_DENIED|Check permissions or file ID.")

    def handle_file_status_change(self, file_id, cmd, target_user=None):
        f = self.db_manager.get_file_record(file_id=file_id, owner_id=self.user_id)
        if not f: return self.send_response("FILE_NOT_FOUND")

        old_path = self.resolve_path(f)
        
        if cmd == self.config['COMMANDS']['MAKE_PUBLIC_USER']:
            self.db_manager.update_file_record(file_id, is_public=True)
            f['is_public'] = True
            
        elif cmd == self.config['COMMANDS']['MAKE_SHARED_USER'] and target_user:
            recipient = self.db_manager.get_user_record(username=target_user)
            if recipient:
                self.db_manager.update_file_record(file_id, is_public=False, recipient_id=recipient['id'])
                f['recipient_id'] = recipient['id']
                f['is_public'] = False
        
        new_path = self.resolve_path(f)
        os.makedirs(os.path.dirname(new_path), exist_ok=True)
        shutil.move(old_path, new_path)
        self.send_response("STATUS_UPDATED")

    def resolve_path(self, record):
        """The generic path resolver used by all handlers."""
        if record.get('is_public'):
            return os.path.join(self.public_files_dir, record['file_name'])
        if record.get('recipient_id'):
            # Fetch recipient name for pathing
            recipient = self.db_manager.get_user_record(user_id=record['recipient_id'])
            recip_name = recipient['username'] if recipient else "unknown"
            return os.path.join(self.shared_uploads_dir, recip_name, record['file_name'])
        return os.path.join(self.upload_dir, self.username, record['file_name'])

    def send_response(self, response):
        self.client_socket.sendall(f"{response}\n".encode('utf-8'))

    def cleanup(self):
        self.client_socket.close()
        logging.info(f"[{self.address}] Connection closed.")