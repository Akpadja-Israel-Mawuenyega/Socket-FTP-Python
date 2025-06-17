# thread_functions.py

import threading
import socket
import tqdm
import os
import sys
import ssl
from server_auth import ServerAuthHandler

class ClientHandler(threading.Thread):
    def __init__(self, client_socket: socket.socket, address: tuple, server_config: dict, auth_handler: ServerAuthHandler): # NEW: Pass auth_handler
        super().__init__()
        self.client_socket = client_socket
        self.address = address
        self.buffer_size = server_config['buffer_size']
        self.separator = server_config['separator']
        self.upload_dir = server_config['upload_dir']
        self.public_files_dir = server_config['public_files_dir'] # Server's public files (now renamed 'public_files')
        self.shared_uploads_dir = server_config['shared_uploads_dir'] # For client-shared files

        # Command constants from server config
        self.UPLOAD_PRIVATE_COMMAND = server_config['UPLOAD_PRIVATE_COMMAND']
        self.DOWNLOAD_SERVER_PUBLIC_COMMAND = server_config['DOWNLOAD_SERVER_PUBLIC_COMMAND']
        self.UPLOAD_FOR_SHARING_COMMAND = server_config['UPLOAD_FOR_SHARING_COMMAND']
        self.LIST_SHARED_COMMAND = server_config['LIST_SHARED_COMMAND']
        self.DOWNLOAD_SHARED_COMMAND = server_config['DOWNLOAD_SHARED_COMMAND']
        self.REGISTER_COMMAND = server_config['REGISTER_COMMAND']
        self.LOGIN_COMMAND = server_config['LOGIN_COMMAND']
        self.LOGOUT_COMMAND = server_config['LOGOUT_COMMAND']
        self.MAKE_PUBLIC_ADMIN_COMMAND = server_config['MAKE_PUBLIC_ADMIN_COMMAND']
        self.PING_COMMAND = "PING"

        # Response constants from server config
        self.DOWNLOAD_START_RESPONSE = server_config['DOWNLOAD_START_RESPONSE']
        self.FILE_NOT_FOUND_RESPONSE = server_config['FILE_NOT_FOUND_RESPONSE']
        self.SHARED_LIST_RESPONSE = server_config['SHARED_LIST_RESPONSE']
        self.NO_FILES_SHARED_RESPONSE = server_config['NO_FILES_SHARED_RESPONSE']
        self.UPLOAD_COMPLETE_RESPONSE = server_config['UPLOAD_COMPLETE_RESPONSE']
        self.UPLOAD_INCOMPLETE_RESPONSE = server_config['UPLOAD_INCOMPLETE_RESPONSE']

        # Authentication Responses
        self.REGISTER_SUCCESS_RESPONSE = server_config['REGISTER_SUCCESS_RESPONSE']
        self.REGISTER_FAILED_RESPONSE = server_config['REGISTER_FAILED_RESPONSE']
        self.LOGIN_SUCCESS_RESPONSE = server_config['LOGIN_SUCCESS_RESPONSE']
        self.LOGIN_FAILED_RESPONSE = server_config['LOGIN_FAILED_RESPONSE']
        self.LOGOUT_SUCCESS_RESPONSE = server_config['LOGOUT_SUCCESS_RESPONSE']
        self.AUTHENTICATION_REQUIRED_RESPONSE = server_config['AUTHENTICATION_REQUIRED_RESPONSE']
        self.PERMISSION_DENIED_RESPONSE = server_config['PERMISSION_DENIED_RESPONSE']
        self.ADMIN_FILE_MAKE_PUBLIC_SUCCESS = server_config['ADMIN_FILE_MAKE_PUBLIC_SUCCESS']
        self.ADMIN_FILE_MAKE_PUBLIC_FAILED = server_config['ADMIN_FILE_MAKE_PUBLIC_FAILED']
        self.INVALID_SESSION_RESPONSE = server_config['INVALID_SESSION_RESPONSE']


        self.auth_handler = auth_handler # NEW: Store the auth handler

        # Paths should be relative to the server.py script's location
        # Re-verify and adjust directory paths to be robust
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.upload_dir = os.path.join(script_dir, self.upload_dir)
        self.public_files_dir = os.path.join(script_dir, self.public_files_dir)
        self.shared_uploads_dir = os.path.join(script_dir, self.shared_uploads_dir)

        self._ensure_dirs_exist()

    def _ensure_dirs_exist(self):
        for directory in [self.upload_dir, self.public_files_dir, self.shared_uploads_dir]:
            if not os.path.exists(directory):
                os.makedirs(directory)
                print(f"[Server] Created directory: {directory}")

    def run(self):
        print(f"[{self.address}] Client connected.")
        try:
            while True:
                # Receive command from client
                # Set a timeout for receiving commands to detect idle connections
                self.client_socket.settimeout(300) # 5 minutes timeout

                try:
                    command_with_args = self.client_socket.recv(self.buffer_size).decode('utf-8')
                except socket.timeout:
                    print(f"[{self.address}] Client idle for 5 minutes. Closing connection.")
                    break
                except (BrokenPipeError, ConnectionResetError):
                    print(f"[{self.address}] Client disconnected unexpectedly.")
                    break
                except ssl.SSLError as e:
                    print(f"[{self.address}] SSL Error during receive: {e}. Closing connection.")
                    break
                except Exception as e:
                    print(f"[{self.address}] Error receiving command: {e}. Closing connection.")
                    break

                if not command_with_args:
                    print(f"[{self.address}] Client disconnected.")
                    break

                parts = command_with_args.split(self.separator)
                command = parts[0]
                session_id = None # Default
                args_start_index = 1 # For non-auth commands, first arg is at index 1

                # Check if command is one that typically has a session ID
                if command in [self.UPLOAD_PRIVATE_COMMAND, self.UPLOAD_FOR_SHARING_COMMAND,
                               self.DOWNLOAD_SERVER_PUBLIC_COMMAND, self.LIST_SHARED_COMMAND,
                               self.DOWNLOAD_SHARED_COMMAND, self.LOGOUT_COMMAND,
                               self.MAKE_PUBLIC_ADMIN_COMMAND]:
                    if len(parts) > 1:
                        session_id = parts[1]
                        args_start_index = 2 # Actual arguments start after session_id
                    else:
                        self._send_response(self.client_socket, self.AUTHENTICATION_REQUIRED_RESPONSE)
                        print(f"[{self.address}] Command '{command}' received without session ID. Authentication required.")
                        continue # Skip to next loop iteration

                current_user = None
                if session_id:
                    current_user = self.auth_handler.authenticate_session(session_id)
                    if not current_user:
                        self._send_response(self.client_socket, self.INVALID_SESSION_RESPONSE)
                        print(f"[{self.address}] Invalid or expired session ID '{session_id[:8]}...' for command '{command}'.")
                        continue # Skip to next loop iteration

                print(f"[{self.address}] Received command: {command} from user {current_user['username'] if current_user else 'UNAUTHENTICATED'}")

                if command == self.REGISTER_COMMAND:
                    if len(parts) == 3:
                        username, password = parts[1], parts[2]
                        self.auth_handler.handle_register(self.client_socket, username, password)
                    else:
                        self._send_response(self.client_socket, f"ERROR{self.separator}Invalid REGISTER command format.")

                elif command == self.LOGIN_COMMAND:
                    if len(parts) == 3:
                        username, password = parts[1], parts[2]
                        self.auth_handler.handle_login(self.client_socket, username, password)
                    else:
                        self._send_response(self.client_socket, f"ERROR{self.separator}Invalid LOGIN command format.")

                elif command == self.LOGOUT_COMMAND:
                    if current_user: # Session was valid and user found
                        self.auth_handler.handle_logout(self.client_socket, session_id)
                    else: # Session was invalid, but client still sent it. Just inform.
                        self._send_response(self.client_socket, self.LOGOUT_SUCCESS_RESPONSE) # Or just silently fail, client clears its state anyway.

                elif command == self.PING_COMMAND:
                    print(f"[{self.address}] Received PING from {current_user['username'] if current_user else 'UNAUTHENTICATED'}. Sending PONG.")
                    self._send_response(self.client_socket, "PONG")
                
                elif command == self.UPLOAD_PRIVATE_COMMAND:
                    if not current_user:
                        self._send_response(self.client_socket, self.AUTHENTICATION_REQUIRED_RESPONSE)
                        continue
                    # Format: UPLOAD_PRIVATE<SEP>session_id<SEP>filename<SEP>filesize
                    if len(parts) == 4:
                        filename, filesize = parts[args_start_index], int(parts[args_start_index + 1])
                        # Private uploads go to a folder specific to the user
                        user_private_upload_dir = os.path.join(self.upload_dir, current_user['username'])
                        os.makedirs(user_private_upload_dir, exist_ok=True) # Ensure user's private dir exists
                        self._receive_file_from_client(self.client_socket, filename, filesize, user_private_upload_dir, is_private=True)
                    else:
                        self._send_response(self.client_socket, f"ERROR{self.separator}Invalid UPLOAD_PRIVATE command format.")


                elif command == self.DOWNLOAD_SERVER_PUBLIC_COMMAND:
                    if not current_user:
                        self._send_response(self.client_socket, self.AUTHENTICATION_REQUIRED_RESPONSE)
                        continue
                    # Format: DOWNLOAD_SERVER_PUBLIC<SEP>session_id<SEP>filename
                    if len(parts) == 3:
                        filename = parts[args_start_index]
                        self._serve_file_to_client(self.client_socket, filename, self.public_files_dir)
                    else:
                        self._send_response(self.client_socket, f"ERROR{self.separator}Invalid DOWNLOAD_SERVER_PUBLIC command format.")


                elif command == self.UPLOAD_FOR_SHARING_COMMAND:
                    if not current_user:
                        self._send_response(self.client_socket, self.AUTHENTICATION_REQUIRED_RESPONSE)
                        continue
                    # Format: UPLOAD_FOR_SHARE<SEP>session_id<SEP>filename<SEP>filesize
                    if len(parts) == 4:
                        filename, filesize = parts[args_start_index], int(parts[args_start_index + 1])
                        # Files for sharing go to shared_uploads_dir
                        self._receive_file_from_client(self.client_socket, filename, filesize, self.shared_uploads_dir, is_private=False)
                    else:
                        self._send_response(self.client_socket, f"ERROR{self.separator}Invalid UPLOAD_FOR_SHARE command format.")


                elif command == self.LIST_SHARED_COMMAND:
                    if not current_user:
                        self._send_response(self.client_socket, self.AUTHENTICATION_REQUIRED_RESPONSE)
                        continue
                    # Format: LIST_SHARED<SEP>session_id
                    # No additional args needed
                    self._handle_list_shared_files(self.client_socket)


                elif command == self.DOWNLOAD_SHARED_COMMAND:
                    if not current_user:
                        self._send_response(self.client_socket, self.AUTHENTICATION_REQUIRED_RESPONSE)
                        continue
                    # Format: DOWNLOAD_SHARED<SEP>session_id<SEP>filename
                    if len(parts) == 3:
                        filename = parts[args_start_index]
                        self._serve_file_to_client(self.client_socket, filename, self.shared_uploads_dir)
                    else:
                        self._send_response(self.client_socket, f"ERROR{self.separator}Invalid DOWNLOAD_SHARED command format.")


                elif command == self.MAKE_PUBLIC_ADMIN_COMMAND:
                    if not current_user:
                        self._send_response(self.client_socket, self.AUTHENTICATION_REQUIRED_RESPONSE)
                        continue
                    # Format: MAKE_PUBLIC_ADMIN<SEP>session_id<SEP>filename
                    if len(parts) == 3:
                        filename = parts[args_start_index]
                        self.auth_handler.handle_make_file_public_admin(self.client_socket, current_user, filename)
                    else:
                        self._send_response(self.client_socket, f"ERROR{self.separator}Invalid MAKE_PUBLIC_ADMIN command format.")

                else:
                    self._send_response(self.client_socket, f"UNKNOWN_COMMAND{self.separator}Unknown command: {command}")
                    print(f"[{self.address}] Unknown command received: {command}")

        except Exception as e:
            print(f"[{self.address}] Error in client handler thread: {e}")
        finally:
            self._close_client_socket()
            print(f"[{self.address}] Connection closed.")


    def _send_response(self, client_socket: socket.socket, response: str):
        """Helper to send encoded response."""
        try:
            client_socket.sendall(response.encode('utf-8'))
        except (BrokenPipeError, ConnectionResetError) as e:
            print(f"Error sending response: Client connection lost. {e}")
        except Exception as e:
            print(f"Error sending response: {e}")

    # ... (rest of existing _receive_file_from_client, _serve_file_to_client, _handle_list_shared_files methods)
    # These remain largely the same, they don't need authentication logic themselves,
    # as authentication is handled before they are called.
    def _receive_file_from_client(self, client_socket: socket.socket, filename: str, filesize: int, destination_dir: str, is_private: bool = False) -> bool:
        filepath = os.path.join(destination_dir, os.path.basename(filename))
        print(f"[{self.address}] Receiving file '{filename}' ({filesize} bytes) to '{filepath}'...")
        self._send_response(client_socket, "READY_FOR_FILE_DATA")

        try:
            progress = tqdm.tqdm(range(filesize), f"Receiving {filename}", unit="B", unit_scale=True, unit_divisor=1024)
            with open(filepath, "wb") as f:
                bytes_received = 0
                while bytes_received < filesize:
                    bytes_to_read = min(filesize - bytes_received, self.buffer_size)
                    bytes_read = client_socket.recv(bytes_to_read)
                    if not bytes_read:
                        print(f"[{self.address}] Warning: Client disconnected during file reception for {filename}. Received {bytes_received}/{filesize} bytes.")
                        break
                    f.write(bytes_read)
                    bytes_received += len(bytes_read)
                    progress.update(len(bytes_read))
            progress.close()

            if bytes_received == filesize:
                self._send_response(client_socket, self.UPLOAD_COMPLETE_RESPONSE)
                print(f"[{self.address}] Successfully received '{filename}'.")
                return True
            else:
                self._send_response(client_socket, self.UPLOAD_INCOMPLETE_RESPONSE)
                print(f"[{self.address}] Incomplete file reception for '{filename}'. Expected {filesize}, got {bytes_received}.")
                # Optional: clean up incomplete file
                if os.path.exists(filepath):
                    os.remove(filepath)
                return False

        except FileNotFoundError:
            self._send_response(client_socket, f"ERROR{self.separator}Server: File path error.")
            print(f"[{self.address}] Error: Could not open file for writing at '{filepath}'. Check permissions.")
            return False
        except OSError as e:
            self._send_response(client_socket, f"ERROR{self.separator}Server: OS error during file write.")
            print(f"[{self.address}] An OS error occurred while writing file to '{filepath}': {e}")
            return False
        except Exception as e:
            self._send_response(client_socket, f"ERROR{self.separator}Server: Unexpected error during file reception.")
            print(f"[{self.address}] An error occurred during file data reception: {e}")
            return False

    def _serve_file_to_client(self, client_socket: socket.socket, requested_filename: str, source_dir: str):
        filepath = os.path.join(source_dir, os.path.basename(requested_filename)) # Ensure no directory traversal
        print(f"[{self.address}] Client requested '{requested_filename}' from '{source_dir}'.")

        if not os.path.exists(filepath) or not os.path.isfile(filepath):
            response = f"{self.FILE_NOT_FOUND_RESPONSE}{self.separator}{requested_filename}".encode('utf-8')
            client_socket.sendall(response)
            print(f"[{self.address}] File '{requested_filename}' not found in '{source_dir}'.")
            return

        filesize = os.path.getsize(filepath)
        response = f"{self.DOWNLOAD_START_RESPONSE}{self.separator}{os.path.basename(filepath)}{self.separator}{filesize}".encode('utf-8')
        client_socket.sendall(response)

        # Wait for client's "READY_TO_RECEIVE_FILE_DATA" acknowledgement
        ack = client_socket.recv(self.buffer_size).decode('utf-8')
        if ack != "READY_TO_RECEIVE_FILE_DATA":
            print(f"[{self.address}] Client did not send READY_TO_RECEIVE_FILE_DATA ack. Aborting download.")
            return

        try:
            progress = tqdm.tqdm(range(filesize), f"Sending {requested_filename}", unit="B", unit_scale=True, unit_divisor=1024)
            with open(filepath, "rb") as f:
                while True:
                    bytes_read = f.read(self.buffer_size)
                    if not bytes_read:
                        break
                    client_socket.sendall(bytes_read)
                    progress.update(len(bytes_read))
            progress.close()
            print(f"[{self.address}] Successfully served '{requested_filename}'. Waiting for client final ack...")

            # Wait for client's final reception confirmation
            client_final_ack = client_socket.recv(self.buffer_size).decode('utf-8')
            if client_final_ack == "CLIENT_RECEPTION_COMPLETE":
                print(f"[{self.address}] Client confirmed complete reception of '{requested_filename}'.")
            else:
                print(f"[{self.address}] Client reported incomplete reception of '{requested_filename}': {client_final_ack}")


        except FileNotFoundError:
            print(f"[{self.address}] Error: File '{requested_filename}' disappeared during serving.")
        except OSError as e:
            print(f"[{self.address}] An OS error occurred while serving file from '{filepath}': {e}")
        except Exception as e:
            print(f"[{self.address}] An unexpected error occurred during file serving in _serve_file_to_client: {e}")

    def _handle_list_shared_files(self, client_socket: socket.socket):
        try:
            shared_files = [f for f in os.listdir(self.shared_uploads_dir) if os.path.isfile(os.path.join(self.shared_uploads_dir, f))]

            if not shared_files:
                response = self.NO_FILES_SHARED_RESPONSE.encode('utf-8')
                client_socket.sendall(response)
                print(f"[{self.address}] No shared files to list.")
                return

            files_list_str = "|||".join(shared_files)

            response = f"{self.SHARED_LIST_RESPONSE}{self.separator}{files_list_str}".encode('utf-8')
            client_socket.sendall(response)
            print(f"[{self.address}] Sent list of shared files.")

        except Exception as e:
            print(f"[{self.address}] Error listing shared files: {e}")
            self._send_response(client_socket, f"ERROR{self.separator}Server error listing shared files.")


    def _close_client_socket(self):
        if self.client_socket:
            try:
                self.client_socket.shutdown(socket.SHUT_RDWR)
                self.client_socket.close()
            except OSError as e:
                if e.errno != 107: # Transport endpoint is not connected
                    print(f"Warning: Error during client socket shutdown/close for {self.address}: {e}")
            except Exception as e:
                print(f"Error closing client socket for {self.address}: {e}")