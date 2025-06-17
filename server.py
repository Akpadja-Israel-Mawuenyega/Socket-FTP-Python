import socket
import ssl
import os
import sys
import threading

from thread_functions import ClientHandler
from user_management import UserDatabaseManager
from server_auth import ServerAuthHandler

class FileTransferServer:
    def __init__(self, host: str, port: int, buffer_size: int = 4096, separator: str = "<SEPARATOR>",
                 upload_dir: str = "uploads", public_files_dir: str = "public_files",
                 shared_uploads_dir: str = "shared_uploads",
                 certfile:str = "server.crt", keyfile:str = "server.key"):
        self.host = host
        self.port = port
        self.buffer_size = buffer_size
        self.separator = separator
        self.upload_dir = upload_dir
        self.public_files_dir = public_files_dir
        self.shared_uploads_dir = shared_uploads_dir

        self.certfile = certfile
        self.keyfile = keyfile

        self.server_socket = None
        self.ssl_context = None

        # Command constants - MUST match client's for consistency
        self.UPLOAD_PRIVATE_COMMAND = "UPLOAD_PRIVATE"
        self.DOWNLOAD_SERVER_PUBLIC_COMMAND = "DOWNLOAD_SERVER_PUBLIC"
        self.UPLOAD_FOR_SHARING_COMMAND = "UPLOAD_FOR_SHARE"
        self.LIST_SHARED_COMMAND = "LIST_SHARED"
        self.DOWNLOAD_SHARED_COMMAND = "DOWNLOAD_SHARED"

        # New Authentication Commands
        self.REGISTER_COMMAND = "REGISTER"
        self.LOGIN_COMMAND = "LOGIN"
        self.LOGOUT_COMMAND = "LOGOUT"
        self.MAKE_PUBLIC_ADMIN_COMMAND = "MAKE_PUBLIC_ADMIN"

        # Response constants - MUST match client's
        self.DOWNLOAD_START_RESPONSE = "DOWNLOAD_START"
        self.FILE_NOT_FOUND_RESPONSE = "FILE_NOT_FOUND"
        self.SHARED_LIST_RESPONSE = "SHARED_LIST"
        self.NO_FILES_SHARED_RESPONSE = "NO_FILES_SHARED"
        self.UPLOAD_COMPLETE_RESPONSE = "UPLOAD_COMPLETE"
        self.UPLOAD_INCOMPLETE_RESPONSE = "UPLOAD_INCOMPLETE"

        # New Authentication Responses
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


        # Store all configurations in a dictionary to pass to ClientHandler
        self.server_config = {
            'buffer_size': self.buffer_size,
            'separator': self.separator,
            'upload_dir': self.upload_dir,
            'public_files_dir': self.public_files_dir,
            'shared_uploads_dir': self.shared_uploads_dir,
            'UPLOAD_PRIVATE_COMMAND': self.UPLOAD_PRIVATE_COMMAND,
            'DOWNLOAD_SERVER_PUBLIC_COMMAND': self.DOWNLOAD_SERVER_PUBLIC_COMMAND,
            'UPLOAD_FOR_SHARING_COMMAND': self.UPLOAD_FOR_SHARING_COMMAND,
            'LIST_SHARED_COMMAND': self.LIST_SHARED_COMMAND,
            'DOWNLOAD_SHARED_COMMAND': self.DOWNLOAD_SHARED_COMMAND,
            'REGISTER_COMMAND': self.REGISTER_COMMAND,
            'LOGIN_COMMAND': self.LOGIN_COMMAND,
            'LOGOUT_COMMAND': self.LOGOUT_COMMAND,
            'MAKE_PUBLIC_ADMIN_COMMAND': self.MAKE_PUBLIC_ADMIN_COMMAND,
            'DOWNLOAD_START_RESPONSE': self.DOWNLOAD_START_RESPONSE,
            'FILE_NOT_FOUND_RESPONSE': self.FILE_NOT_FOUND_RESPONSE,
            'SHARED_LIST_RESPONSE': self.SHARED_LIST_RESPONSE,
            'NO_FILES_SHARED_RESPONSE': self.NO_FILES_SHARED_RESPONSE,
            'UPLOAD_COMPLETE_RESPONSE': self.UPLOAD_COMPLETE_RESPONSE,
            'UPLOAD_INCOMPLETE_RESPONSE': self.UPLOAD_INCOMPLETE_RESPONSE,
            'REGISTER_SUCCESS_RESPONSE': self.REGISTER_SUCCESS_RESPONSE,
            'REGISTER_FAILED_RESPONSE': self.REGISTER_FAILED_RESPONSE,
            'LOGIN_SUCCESS_RESPONSE': self.LOGIN_SUCCESS_RESPONSE,
            'LOGIN_FAILED_RESPONSE': self.LOGIN_FAILED_RESPONSE,
            'LOGOUT_SUCCESS_RESPONSE': self.LOGOUT_SUCCESS_RESPONSE,
            'AUTHENTICATION_REQUIRED_RESPONSE': self.AUTHENTICATION_REQUIRED_RESPONSE,
            'PERMISSION_DENIED_RESPONSE': self.PERMISSION_DENIED_RESPONSE,
            'ADMIN_FILE_MAKE_PUBLIC_SUCCESS': self.ADMIN_FILE_MAKE_PUBLIC_SUCCESS,
            'ADMIN_FILE_MAKE_PUBLIC_FAILED': self.ADMIN_FILE_MAKE_PUBLIC_FAILED,
            'INVALID_SESSION_RESPONSE': self.INVALID_SESSION_RESPONSE,
        }

        self._create_directories()
        self._setup_ssl_context()

        # NEW: Initialize UserDatabaseManager and ServerAuthHandler
        self.user_db_manager = UserDatabaseManager()
        self.server_auth_handler = ServerAuthHandler(self.user_db_manager, self.separator, self.public_files_dir)


    def _create_directories(self):
        # Create necessary directories if they don't exist
        for directory in [self.upload_dir, self.public_files_dir, self.shared_uploads_dir]:
            if not os.path.exists(directory):
                try:
                    os.makedirs(directory)
                    print(f"Created server directory: '{directory}'")
                except OSError as e:
                    print(f"Error creating server directory '{directory}': {e}")
                    sys.exit(1)

    def _setup_ssl_context(self):
        try:
            self.ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            self.ssl_context.load_cert_chain(certfile=self.certfile, keyfile=self.keyfile)
            print(f"SSL Context initialized. Using server cert: {self.certfile}")
        except FileNotFoundError as e:
            print(f"Error: SSL certificate or key file not found: {e}. Ensure '{self.certfile}' and '{self.keyfile}' exist.")
            sys.exit(1)
        except ssl.SSLError as e:
            print(f"Error setting up SSL context: {e}")
            print("Ensure your certificate and key files are valid and not corrupted.")
            sys.exit(1)

    def start(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5) # Max 5 queued connections
            print(f"[*] Listening on {self.host}:{self.port} (SSL/TLS)")

            while True:
                client_socket, address = self.server_socket.accept()
                print(f"[+] Accepted connection from {address}")
                try:
                    secure_client_socket = self.ssl_context.wrap_socket(client_socket, server_side=True)
                    print(f"[+] SSL Handshake successful with {address}. Spawning new thread...")

                    # NEW: Pass the ServerAuthHandler instance to the ClientHandler
                    handler = ClientHandler(secure_client_socket, address, self.server_config, self.server_auth_handler)
                    handler.start()

                except ssl.SSLError as e:
                    print(f"[-] SSL Handshake failed with {address}: {e}")
                    client_socket.close()
                    continue
                except Exception as e:
                    print(f"An error occurred during client handling setup for {address}: {e}")
                    client_socket.close()

        except socket.error as e:
            print(f"Socket error: {e}")
            print("Ensure the port is not already in use and you have permissions to bind.")
        except KeyboardInterrupt:
            print("\nShutting down server...")
        except Exception as e:
            print(f"An unexpected server error occurred: {e}")
        finally:
            self.close_server()

    def close_server(self):
        if self.server_socket:
            print("Closing server socket...")
            self.server_socket.close()
            self.server_socket = None
            print("Server socket closed.")

if __name__ == "__main__":
    SERVER_HOST = "0.0.0.0"
    SERVER_PORT = 8080

    server = FileTransferServer(SERVER_HOST, SERVER_PORT,
                                certfile="server.crt", keyfile="server.key",
                                public_files_dir="public_files") 
    server.start()