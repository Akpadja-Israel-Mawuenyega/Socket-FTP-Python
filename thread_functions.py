import threading
import socket
import shutil
import os
import logging
from server_auth import ServerAuthHandler
from user_management import DatabaseManager

class ClientHandler(threading.Thread):
    def __init__(self, client_socket: socket.socket, address: tuple, server_config: dict, auth_handler: ServerAuthHandler, db_manager: DatabaseManager):
        threading.Thread.__init__(self)
        self.client_socket = client_socket
        self.address = address
        self.config = server_config
        self.auth_handler = auth_handler
        self.db_manager = db_manager
        
        # Directory mapping from config
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
        
        # Pre-cache command/response dictionaries for cleaner access
        self.cmds = self.config['COMMANDS']
        self.response = self.config['RESPONSES']
        
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

                # --- 1. Session-less Commands (Register / Login) ---
                if command == self.cmds['REGISTER']:
                    self.send_response(self.auth_handler.register_user(parts[1], parts[2]))
                    continue
                
                if command == self.cmds['LOGIN']:
                    response = self.auth_handler.login_user(parts[1], parts[2])
                    if response.startswith(self.response['LOGIN_SUCCESS']):
                        _, self.session_id, self.username, self.user_role, self.user_id = response.split(self.separator)
                        os.makedirs(os.path.join(self.upload_dir, self.username), exist_ok=True)
                    self.send_response(response)
                    continue

                # --- 2. Session Validation ---
                # Check if session_id (parts[1]) is valid
                # Extract session_id (should always be parts[1] after login)
                session_id = parts[1] if len(parts) > 1 else None

                if not session_id or not self.auth_handler.is_valid_session(session_id):
                    self.send_response(self.response['INVALID_SESSION'])
                    continue

                # Update session data
                session_data = self.auth_handler.get_session_data(session_id)
                self.session_id = session_id
                self.username = session_data['username']
                self.user_role = session_data['role']
                self.user_id = session_data['user_id']
                
                # --- 3. Authenticated Commands ---
                
                # LISTING
                if command in [self.cmds['LIST_PRIVATE'], self.cmds['LIST_PUBLIC'], self.cmds['LIST_SHARED']]:
                    self.handle_file_list(command)

                # DOWNLOAD
                elif command in [self.cmds['DOWNLOAD_PRIVATE'], self.cmds['DOWNLOAD_SHARED'], self.cmds['DOWNLOAD_SERVER_PUBLIC']]:
                    self.handle_file_download(parts[2])

                # UPLOAD
                elif command in [self.cmds['UPLOAD_PRIVATE'], self.cmds['UPLOAD_PUBLIC'], self.cmds['UPLOAD_FOR_SHARING']]:
                    recipient = parts[2] if command == self.cmds['UPLOAD_FOR_SHARING'] else None
                    self.handle_file_upload(command, parts, recipient)

                # DELETE
                elif command in [self.cmds.get('DELETE_FILE', 'DELETE_FILE'), self.cmds['ADMIN_DELETE_FILE']]:
                    is_admin_req = (command == self.cmds['ADMIN_DELETE_FILE'])
                    self.handle_file_delete(parts[2], is_admin_req)

                # SHARE / VISIBILITY
                elif command in [self.cmds['MAKE_PUBLIC_USER'], self.cmds['MAKE_SHARED_USER']]:
                    target = parts[3] if len(parts) > 3 else None
                    self.handle_file_status_change(parts[2], command, target)

                # LOGOUT / QUIT
                elif command == self.cmds['LOGOUT'] or command == self.cmds['QUIT']:
                    self.auth_handler.logout_user(self.session_id)
                    if command == self.cmds['LOGOUT']:
                        self.send_response(self.response['LOGOUT_SUCCESS'])
                    break

            except Exception as e:
                logging.error(f"Command Error: {e}", exc_info=True)
                self.send_response(f"{self.response['ERROR']}{self.separator}Internal server error.")

    # --- GENERIC IMPLEMENTATIONS USING CONFIG ---

    def handle_file_list(self, cmd):
        query_map = {
            self.cmds['LIST_PUBLIC']: {'is_public': True},
            self.cmds['LIST_SHARED']: {'recipient_id': self.user_id, 'is_public': False},
            self.cmds['LIST_PRIVATE']: {'owner_id': self.user_id, 'is_public': False}
        }

        filters = query_map.get(cmd, {'owner_id': self.user_id})
        files = self.db_manager.get_files(**filters)

        if not files:
            empty_key = 'NO_FILES_PUBLIC' if 'PUBLIC' in cmd else 'NO_FILES_PRIVATE'
            self.send_response(self.response.get(empty_key, "LIST_EMPTY"))
        else:
            flat_list = []
            for f in files:
                flat_list.append(str(f['file_id']))
                flat_list.append(f['file_name'])
            
            data_string = self.separator.join(flat_list)
            
            self.send_response(f"{self.response['LIST_SUCCESS']}{self.separator}{data_string}")
    
    def handle_file_upload(self, cmd, parts, recipient_username=None):
        try:
            file_name = os.path.basename(parts[-2])
            file_size = int(parts[-1])
            
            is_public = (cmd == self.cmds['UPLOAD_PUBLIC'])
            recipient_id = None
            if recipient_username:
                recip_record = self.db_manager.get_user_record(username=recipient_username)
                recipient_id = recip_record['id'] if recip_record else None

            temp_record = {'file_name': file_name, 'is_public': is_public, 'recipient_id': recipient_id}
            dest_path = self.resolve_path(temp_record)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            self.send_response(self.response['READY_FOR_DATA'])
            
            with open(dest_path, "wb") as f:
                received = 0
                while received < file_size:
                    chunk = self.client_socket.recv(min(self.buffer_size, file_size - received))
                    if not chunk: break
                    f.write(chunk)
                    received += len(chunk)

            if received == file_size:
                f = self.db_manager.add_file_record(self.user_id, file_name, file_size, is_public, recipient_id)
                if f:    
                    self.send_response(self.response['UPLOAD_SUCCESS'])
                else:
                    self.send_response(self.response['UPLOAD_FAILED'])
            else:
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                    logging.warning(f"Removed orphaned file {dest_path} due to DB insert failure")
                self.send_response(self.response['UPLOAD_FAILED'])
        except Exception as e:
            self.send_response(f"{self.response['ERROR']}{self.separator}{str(e)}")

    def handle_file_download(self, file_id):
        f = self.db_manager.get_file_record(file_id=file_id)
        if not f:
            return self.send_response(self.response['FILE_NOT_FOUND'])

        can_access = (f['is_public'] or f['owner_id'] == self.user_id or 
                      f['recipient_id'] == self.user_id or self.user_role == 'admin')

        if not can_access:
            return self.send_response(self.response['PERMISSION_DENIED'])

        path = self.resolve_path(f)
        if os.path.exists(path):
            self.send_response(f"{self.response['DOWNLOAD_READY']}{self.separator}{f['file_name']}{self.separator}{f['file_size']}")
            with open(path, "rb") as src:
                self.client_socket.sendfile(src)
        else:
            self.send_response(self.response['FILE_NOT_FOUND'])

    def handle_file_delete(self, file_id, is_admin_req):
        f = self.db_manager.get_file_record(file_id=file_id)
        if not f:
            return self.send_response(self.response['FILE_NOT_FOUND'])

        can_delete = False
        
        if f['owner_id'] == self.user_id:
            can_delete = True
        
        elif self.user_role == 'admin' and is_admin_req and f.get('is_public'):
            can_delete = True
                
        if not can_delete:
            return self.send_response(self.response['PERMISSION_DENIED'])

        if self.db_manager.delete_file_record(file_id):
            path = self.resolve_path(f)
            if os.path.exists(path):
                os.remove(path)
            
            response_key = 'ADMIN_DELETE_SUCCESS' if is_admin_req else 'DELETE_SUCCESS'
            self.send_response(self.response.get(response_key))
        else:
            response_key = 'ADMIN_DELETE_FAILED' if is_admin_req else 'DELETE_FAILED'
            self.send_response(self.response.get(response_key))

    def handle_file_status_change(self, file_id, cmd, target_user=None):
        f = self.db_manager.get_file_record(file_id=file_id, owner_id=self.user_id)
        if not f: 
            return self.send_response(self.response['FILE_NOT_FOUND'])

        new_is_public = f['is_public']
        new_recipient_id = f['recipient_id']
        success_msg = ""

        if cmd == self.cmds['MAKE_PUBLIC_USER']:
            new_is_public = True
            new_recipient_id = None
            success_msg = self.response['USER_PUBLIC_SUCCESS']
        elif cmd == self.cmds['MAKE_SHARED_USER'] and target_user:
            recipient = self.db_manager.get_user_record(username=target_user)
            if not recipient:
                return self.send_response(f"{self.response['ERROR']}{self.separator}Recipient not found.")
            new_is_public = False
            new_recipient_id = recipient['id']
            success_msg = self.response['USER_SHARED_SUCCESS']
        else:
            return self.send_response(f"{self.response['ERROR']}{self.separator}Invalid action.")

        old_path = self.resolve_path(f)
        temp_f = f.copy()
        temp_f['is_public'] = new_is_public
        temp_f['recipient_id'] = new_recipient_id
        new_path = self.resolve_path(temp_f)

        if old_path == new_path:
            return self.send_response(success_msg)

        try:
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            if os.path.exists(new_path):
                return self.send_response(f"{self.response['ERROR']}{self.separator}File name conflict in destination.")
            
            shutil.move(old_path, new_path)
            self.db_manager.update_file_record(file_id, is_public=new_is_public, recipient_id=new_recipient_id)
            self.send_response(success_msg)
        except Exception as e:
            logging.error(f"Status change failed: {e}")
            self.send_response(f"{self.response['ERROR']}{self.separator}Storage operation failed.")

    def resolve_path(self, record):
        if record.get('is_public'):
            return os.path.join(self.public_files_dir, record['file_name'])
        if record.get('recipient_id'):
            recipient = self.db_manager.get_user_record(user_id=record['recipient_id'])
            recip_name = recipient['username'] if recipient else "unknown"
            return os.path.join(self.shared_uploads_dir, recip_name, record['file_name'])
        return os.path.join(self.upload_dir, self.username, record['file_name'])

    def send_response(self, response):
        self.client_socket.sendall(f"{response}{self.separator}".encode('utf-8'))

    def cleanup(self):
        self.client_socket.close()
        logging.info(f"[{self.address}] Connection closed.")