import socket 
import ssl
import os
import sys
import threading

from thread_functions import ClientHandler # Allows client multithreading. These clients communicate via IPC

class FileTransferServer:
    def __init__(self, host: str, port: int, buffer_size: int = 4096, separator: str = "<SEPARATOR>", 
                 upload_dir: str = "uploads", shared_files_dir: str = "shared_files", 
                 shared_uploads_dir: str = "shared_uploads", 
                 certfile:str = "server.crt", keyfile:str = "server.key"): # New directory
        self.host = host
        self.port = port
        self.buffer_size = buffer_size
        self.separator = separator
        self.upload_dir = upload_dir
        self.shared_files_dir = shared_files_dir
        self.shared_uploads_dir = shared_uploads_dir # New
        
        self.certfile = certfile
        self.keyfile = keyfile

        self.server_socket = None
        self.ssl_context = None # Stores the SSL context
        
        # Command constants
        self.UPLOAD_PRIVATE_COMMAND = "UPLOAD_PRIVATE"           # Original upload
        self.DOWNLOAD_SERVER_PUBLIC_COMMAND = "DOWNLOAD_SERVER_PUBLIC" # Original download
        self.UPLOAD_FOR_SHARING_COMMAND = "UPLOAD_FOR_SHARE"     # New: Client uploads for others
        self.LIST_SHARED_COMMAND = "LIST_SHARED"                 # New: Client requests list of shared files
        self.DOWNLOAD_SHARED_COMMAND = "DOWNLOAD_SHARED"         # New: Client downloads a shared file
        
        self.DOWNLOAD_START_RESPONSE = "DOWNLOAD_START"          # Response for starting download
        self.FILE_NOT_FOUND_RESPONSE = "FILE_NOT_FOUND"          # Response for file not found
        self.SHARED_LIST_RESPONSE = "SHARED_LIST"                # New: Response for shared file list
        self.NO_FILES_SHARED_RESPONSE = "NO_FILES_SHARED"        # New: Response when no shared files

        self._create_directories()
        self._setup_ssl_context()

        # Store server configurations to pass to client handlers
        self.server_config = {
            'buffer_size': self.buffer_size,
            'separator': self.separator,
            'upload_dir': self.upload_dir,
            'shared_files_dir': self.shared_files_dir,
            'shared_uploads_dir': self.shared_uploads_dir, # Pass new directory
            
            'UPLOAD_PRIVATE_COMMAND': self.UPLOAD_PRIVATE_COMMAND,
            'DOWNLOAD_SERVER_PUBLIC_COMMAND': self.DOWNLOAD_SERVER_PUBLIC_COMMAND,
            'UPLOAD_FOR_SHARING_COMMAND': self.UPLOAD_FOR_SHARING_COMMAND,
            'LIST_SHARED_COMMAND': self.LIST_SHARED_COMMAND,
            'DOWNLOAD_SHARED_COMMAND': self.DOWNLOAD_SHARED_COMMAND,
            
            'DOWNLOAD_START_RESPONSE': self.DOWNLOAD_START_RESPONSE,
            'FILE_NOT_FOUND_RESPONSE': self.FILE_NOT_FOUND_RESPONSE,
            'SHARED_LIST_RESPONSE': self.SHARED_LIST_RESPONSE,
            'NO_FILES_SHARED_RESPONSE': self.NO_FILES_SHARED_RESPONSE,
        }

    def _create_directories(self):
        # Include the new directory in creation list
        for directory in [self.upload_dir, self.shared_files_dir, self.shared_uploads_dir]:
            if not os.path.exists(directory):
                try:
                    os.makedirs(directory)
                    print(f"Created directory: '{directory}'")
                except OSError as e:
                    print(f"Error creating directory '{directory}': {e}")
                    sys.exit(1)
    
    def _setup_ssl_context(self):
        # Helper method to create and configures the SSLContext for the server.
        try:
            self.ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            self.ssl_context.load_cert_chain(certfile=self.certfile, keyfile=self.keyfile)
            print(f"SSL Context initialized with {self.certfile} and {self.keyfile}")
        except FileNotFoundError:
            print(f"Error: SSL certificate or key file not found. Ensure '{self.certfile}' and '{self.keyfile}' exist in the server directory.")
            sys.exit(1)
        except ssl.SSLError as e:
            print(f"Error setting up SSL context: {e}")
            print("Ensure your certificate and key files are valid and not corrupted.")
            sys.exit(1)             

    def start(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            print(f"[*] Listening as {self.host}:{self.port}")
            print(f"Private uploads to: {self.upload_dir}")
            print(f"Public files for download from server: {self.shared_files_dir}")
            print(f"Files uploaded for sharing: {self.shared_uploads_dir}") # New

            while True:
                print("\nWaiting for a client connection...")
                client_socket, address = self.server_socket.accept()
                print(f"[+] {address} connected. Spawning new thread...")
                
                try: 
                    secure_client_socket = self.ssl_context.wrap_socket(client_socket, server_side=True)
                    print(f"[+] SSL Handshake successful with {address}. Spawning new thread...")
                    
                    handler = ClientHandler(secure_client_socket, address, self.server_config)
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

    server = FileTransferServer(SERVER_HOST, SERVER_PORT, certfile="server.crt", keyfile="server.key")
    server.start()
