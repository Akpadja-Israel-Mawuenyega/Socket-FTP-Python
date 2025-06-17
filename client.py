import socket
import tqdm
import os
import sys
import ssl
import requests
from urllib.parse import urlparse
import time

from client_auth import ClientAuthHandler

class FileTransferClient:
    def __init__(self, host: str, port: int, buffer_size: int = 4096, separator: str = "<SEPARATOR>",
                 download_dir: str = "downloads", server_cert: str = 'server.crt',
                 client_cert: str = None, client_key: str = None):
        self.host = host
        self.port = port
        self.buffer_size = buffer_size
        self.separator = separator
        self.s = None
        self.secure_socket = None
        self.download_dir = download_dir
        self.server_cert = server_cert
        self.client_cert = client_cert   # Optional but use if you want mTLS
        self.client_key = client_key     # Optional but use if you want mTLS

        # Command constants
        self.UPLOAD_PRIVATE_COMMAND = "UPLOAD_PRIVATE"
        self.DOWNLOAD_SERVER_PUBLIC_COMMAND = "DOWNLOAD_SERVER_PUBLIC"
        self.UPLOAD_FOR_SHARING_COMMAND = "UPLOAD_FOR_SHARE"
        self.LIST_SHARED_COMMAND = "LIST_SHARED"
        self.DOWNLOAD_SHARED_COMMAND = "DOWNLOAD_SHARED"

        # Authentication Commands
        self.REGISTER_COMMAND = "REGISTER"
        self.LOGIN_COMMAND = "LOGIN"
        self.LOGOUT_COMMAND = "LOGOUT"
        self.MAKE_PUBLIC_ADMIN_COMMAND = "MAKE_PUBLIC_ADMIN"

        # Response constants
        self.DOWNLOAD_START_RESPONSE = "DOWNLOAD_START"
        self.FILE_NOT_FOUND_RESPONSE = "FILE_NOT_FOUND"
        self.SHARED_LIST_RESPONSE = "SHARED_LIST"
        self.NO_FILES_SHARED_RESPONSE = "NO_FILES_SHARED"
        self.UPLOAD_COMPLETE_RESPONSE = "UPLOAD_COMPLETE"
        self.UPLOAD_INCOMPLETE_RESPONSE = "UPLOAD_INCOMPLETE"
        self.PONG_RESPONSE = "PONG"

        # Authentication Responses
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


        self._create_download_directory()
        self._setup_ssl_context()

        # Authentication State
        self.session_id = None
        self.username = None
        self.user_role = None

        self.auth_handler = ClientAuthHandler(self)

    def _create_download_directory(self):
        if not os.path.exists(self.download_dir):
            try:
                os.makedirs(self.download_dir)
                print(f"Created download directory: '{self.download_dir}'")
            except OSError as e:
                print(f"Error creating download directory '{self.download_dir}': {e}")
                sys.exit(1)

    def _setup_ssl_context(self):
        try:
            self.ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            self.ssl_context.load_verify_locations(self.server_cert)
            if self.client_cert and self.client_key:
                self.ssl_context.load_cert_chain(certfile=self.client_cert, keyfile=self.client_key)
            self.ssl_context.check_hostname = False
            print(f"SSL Context initialized. Trusting server cert: {self.server_cert}")
        except FileNotFoundError as e:
            print(f"Error: SSL certificate file not found: {e}. Ensure '{self.server_cert}' exists.")
            sys.exit(1)
        except ssl.SSLError as e:
            print(f"Error setting up SSL context: {e}")
            print("Ensure your certificate files are valid and not corrupted.")
            sys.exit(1)

    def _connect(self, attempt_redetection=False):
        if self.secure_socket:
            try:
                self.secure_socket.sendall(b"PING")
                pong_response = self.secure_socket.recv(self.buffer_size).decode('utf-8')
                if pong_response == self.PONG_RESPONSE:
                    return True
                else:
                    print(f"Ping check failed: Expected '{self.PONG_RESPONSE}', but received '{pong_response}'. Reconnecting...")
                    self._close_connection()
            except (BrokenPipeError, ConnectionResetError, ssl.SSLError, socket.error) as e:
                print(f"Existing connection lost during PING check: {e}. Attempting to reconnect...")
                self._close_connection()
            except socket.timeout:
                print("Existing connection timed out during PING check. Attempting to reconnect...")
                self._close_connection()
            except Exception as e:
                print(f"An unexpected error occurred during PING check: {e}. Attempting to reconnect...")
                self._close_connection()

        for attempt in range(3):
            try:
                self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.secure_socket = self.ssl_context.wrap_socket(self.s, server_hostname=self.host)
                self.secure_socket.connect((self.host, self.port))
                print(f"[*] Connected to {self.host}:{self.port} (SSL/TLS)")
                return True
            except ConnectionRefusedError:
                print(f"[-] Connection refused for {self.host}:{self.port}. Server might not be running or address is incorrect.")
            except ssl.SSLError as e:
                print(f"[-] SSL/TLS Handshake failed for {self.host}:{self.port}: {e}. Check server certificate and client trust.")
            except socket.gaierror:
                print(f"[-] Hostname resolution failed for {self.host}. Check server address.")
            except Exception as e:
                print(f"[-] An unexpected error occurred during connection to {self.host}:{self.port}: {e}")

            print(f"Retrying connection... ({attempt + 1}/3)")
            time.sleep(2) # Wait a bit before retrying

            if attempt_redetection and attempt == 0: # Only try to redetect on first failed retry
                print("Attempting to redetect ngrok address...")
                new_host, new_port = _get_ngrok_public_address()
                if new_host and new_port and (new_host != self.host or new_port != self.port):
                    print(f"Detected new ngrok address: {new_host}:{new_port}. Updating client configuration.")
                    self.host = new_host
                    self.port = new_port
                else:
                    print("No new ngrok address detected or it's the same. Sticking with current configuration.")

        print("Failed to establish connection after multiple attempts.")
        self._close_connection()
        return False

    def _close_connection(self):
        if self.secure_socket:
            try:
                self.secure_socket.shutdown(socket.SHUT_RDWR)
                self.secure_socket.close()
            except OSError as e:
                if e.errno != 107:
                    print(f"Warning: Error during SSL socket shutdown/close: {e}")
            except Exception as e:
                print(f"Error closing secure socket: {e}")
            self.secure_socket = None
        if self.s:
            self.s.close()
            self.s = None

    def _send_command(self, command_str: str) -> str:
        # Pass True to attempt_redetection for dynamic address update
        if not self._connect(attempt_redetection=True):
            return f"ERROR{self.separator}NO_CONNECTION"

        try:
            if self.session_id and command_str not in [self.REGISTER_COMMAND, self.LOGIN_COMMAND]:
                command_str_with_session = f"{command_str.split(self.separator, 1)[0]}{self.separator}{self.session_id}"
                if self.separator in command_str:
                    command_str_with_session += self.separator + command_str.split(self.separator, 1)[1]
                command_to_send = command_str_with_session
            else:
                command_to_send = command_str

            self.secure_socket.sendall(command_to_send.encode('utf-8'))
            response = self.secure_socket.recv(self.buffer_size).decode('utf-8')
            return response
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError) as e:
            print(f"Error sending command or receiving response: {e}. Connection may be lost.")
            self._close_connection()
            return f"ERROR{self.separator}CONNECTION_LOST"
        except socket.timeout:
            print("Socket timeout during command send/recv.")
            self._close_connection()
            return f"ERROR{self.separator}TIMEOUT"
        except Exception as e:
            print(f"An unexpected error occurred during command sending: {e}")
            self._close_connection()
            return f"ERROR{self.separator}GENERAL_ERROR"

    def _receive_file_data(self, secure_socket: ssl.SSLSocket, filepath: str, filesize: int, display_filename: str) -> bool:
        try:
            progress = tqdm.tqdm(range(filesize), f"Receiving {os.path.basename(display_filename)}", unit="B", unit_scale=True, unit_divisor=1024, leave=True)
            with open(filepath, "wb") as f:
                bytes_received = 0
                while bytes_received < filesize:
                    bytes_to_read = min(filesize - bytes_received, self.buffer_size)
                    bytes_read = secure_socket.recv(bytes_to_read)
                    if not bytes_read:
                        print(f"Warning: Connection broken during file reception for {display_filename} (received {bytes_received}/{filesize} bytes).")
                        break
                    f.write(bytes_read)
                    bytes_received += len(bytes_read)
                    progress.update(len(bytes_read))
            progress.close()

            if bytes_received == filesize:
                print(f"Successfully received '{display_filename}' and saved to '{filepath}'.")
                return True
            else:
                print(f"Warning: Received {bytes_received} bytes, expected {filesize} bytes for '{display_filename}'. File might be incomplete.")
                return False

        except FileNotFoundError:
            print(f"Error: Could not open file for writing at '{filepath}'. Check permissions.")
            return False
        except OSError as e:
            print(f"An OS error occurred while writing file to '{filepath}': {e}")
            return False
        except Exception as e:
            print(f"An error occurred during file data reception: {e}")
            return False

    def _send_file_to_server(self, command: str, filepath: str) -> bool:
        filename = os.path.basename(filepath)
        filesize = os.path.getsize(filepath)

        command_str = f"{command}{self.separator}{filename}{self.separator}{filesize}"

        response = self._send_command(command_str)

        if response == "READY_FOR_FILE_DATA":
            print(f"Server is ready to receive {filename}. Sending data...")
            try:
                progress = tqdm.tqdm(range(filesize), f"Sending {filename}", unit="B", unit_scale=True, unit_divisor=1024)
                with open(filepath, "rb") as f:
                    while True:
                        bytes_read = f.read(self.buffer_size)
                        if not bytes_read:
                            break
                        self.secure_socket.sendall(bytes_read)
                        progress.update(len(bytes_read))
                progress.close()
                print(f"File '{filename}' data sent. Waiting for server confirmation...")

                final_response = self.secure_socket.recv(self.buffer_size).decode('utf-8')
                if final_response == self.UPLOAD_COMPLETE_RESPONSE:
                    print(f"Server confirmed '{filename}' upload complete.")
                    return True
                else:
                    print(f"Server reported upload issue for '{filename}': {final_response}")
                    return False

            except FileNotFoundError:
                print(f"Error: File '{filepath}' not found locally.")
                return False
            except OSError as e:
                print(f"An OS error occurred while reading file '{filepath}': {e}")
                return False
            except (BrokenPipeError, ConnectionResetError, ssl.SSLError) as e:
                print(f"Error sending file data: {e}. Connection lost.")
                self._close_connection()
                return False
            except Exception as e:
                print(f"An unexpected error occurred during file upload: {e}")
                self._close_connection()
                return False
        elif response.startswith("ERROR"):
            print(f"Server denied upload or encountered an error: {response}")
            return False
        else:
            print(f"Unexpected response from server: {response}")
            return False

    def _receive_file_from_server(self, command: str, filename: str) -> bool:
        command_str = f"{command}{self.separator}{filename}"
        response = self._send_command(command_str)

        if response.startswith(self.DOWNLOAD_START_RESPONSE):
            parts = response.split(self.separator, 2)
            if len(parts) == 3:
                server_filename = parts[1]
                filesize = int(parts[2])
                download_filepath = os.path.join(self.download_dir, os.path.basename(server_filename))

                print(f"Server is sending '{server_filename}' ({filesize} bytes).")
                self.secure_socket.sendall("READY_TO_RECEIVE_FILE_DATA".encode('utf-8')) # Acknowledge readiness

                received_ok = self._receive_file_data(self.secure_socket, download_filepath, filesize, server_filename)

                if received_ok:
                    self.secure_socket.sendall("CLIENT_RECEPTION_COMPLETE".encode('utf-8'))
                    return True
                else:
                    self.secure_socket.sendall("CLIENT_RECEPTION_INCOMPLETE".encode('utf-8'))
                    return False
            else:
                print(f"Error: Malformed DOWNLOAD_START response from server: {response}")
                return False
        elif response.startswith(self.FILE_NOT_FOUND_RESPONSE):
            parts = response.split(self.separator, 1)
            print(f"Server reported: File '{parts[1] if len(parts) > 1 else filename}' not found.")
            return False
        elif response.startswith(self.AUTHENTICATION_REQUIRED_RESPONSE):
            print("Authentication required. Please log in.")
            return False
        elif response.startswith(self.INVALID_SESSION_RESPONSE):
            print("Your session is invalid or expired. Please log in again.")
            self.session_id = None
            self.username = None
            self.user_role = None
            return False
        elif response.startswith("ERROR"):
            print(f"Server error during download request: {response}")
            return False
        else:
            print(f"Unexpected response from server for download: {response}")
            return False

    def upload_private_file(self):
        if not self.session_id:
            print("Please log in to upload private files.")
            return
        filepath = input("Enter the path to the file you want to upload privately: ")
        if not os.path.exists(filepath):
            print("File not found.")
            return
        if self._send_file_to_server(self.UPLOAD_PRIVATE_COMMAND, filepath):
            print("Private file upload initiated.")

    def upload_for_sharing(self):
        if not self.session_id:
            print("Please log in to upload files for sharing.")
            return
        filepath = input("Enter the path to the file you want to upload for sharing: ")
        if not os.path.exists(filepath):
            print("File not found.")
            return
        if self._send_file_to_server(self.UPLOAD_FOR_SHARING_COMMAND, filepath):
            print("File upload for sharing initiated.")

    def list_and_download_shared_files(self):
        if not self.session_id:
            print("Please log in to list and download shared files.")
            return
        response = self._send_command(self.LIST_SHARED_COMMAND)

        if response.startswith(self.SHARED_LIST_RESPONSE):
            parts = response.split(self.separator, 1)
            files_str = parts[1]
            shared_files = files_str.split("|||")
            print("\n--- Shared Files Available ---")
            for i, file_name in enumerate(shared_files):
                print(f"{i+1}. {file_name}")
            print("------------------------------")

            while True:
                choice = input("Enter the number of the file to download (or 'b' to go back): ")
                if choice.lower() == 'b':
                    break
                try:
                    index = int(choice) - 1
                    if 0 <= index < len(shared_files):
                        filename_to_download = shared_files[index]
                        self._receive_file_from_server(self.DOWNLOAD_SHARED_COMMAND, filename_to_download)
                        break
                    else:
                        print("Invalid number. Please try again.")
                except ValueError:
                    print("Invalid input. Please enter a number or 'b'.")
        elif response == self.NO_FILES_SHARED_RESPONSE:
            print("No shared files currently available.")
        elif response.startswith(self.AUTHENTICATION_REQUIRED_RESPONSE):
            print("Authentication required. Please log in.")
        elif response.startswith(self.INVALID_SESSION_RESPONSE):
            print("Your session is invalid or expired. Please log in again.")
            self.session_id = None
            self.username = None
            self.user_role = None
        elif response.startswith("ERROR"):
            print(f"Error listing shared files: {response}")
        else:
            print(f"Unexpected response from server: {response}")

    def download_server_public_file(self):
        if not self.session_id:
            print("Please log in to download server public files.")
            return
        filename = input("Enter the name of the public file on the server to download: ")
        self._receive_file_from_server(self.DOWNLOAD_SERVER_PUBLIC_COMMAND, filename)

    def run_client(self):
        print("\n--- File Transfer Client ---")
        while True:
            status = f"Status: {'Logged in as ' + self.username + ' (' + self.user_role + ')' if self.session_id else 'Not Logged In'}"
            print(f"\n{status}")
            print("1. Register")
            print("2. Login")

            if self.session_id:
                print("3. Upload Private File")
                print("4. Upload File for Sharing")
                print("5. List & Download Shared Files")
                print("6. Download Server Public File")
                if self.user_role == 'admin':
                    print("7. Make File Public (Admin)")
                print("L. Logout")
            print("Q. Quit")

            choice = input("Enter your choice: ").strip().upper()

            if choice == '1':
                self.auth_handler.register_user()
            elif choice == '2':
                self.auth_handler.login_user()
            elif choice == '3' and self.session_id:
                self.upload_private_file()
            elif choice == '4' and self.session_id:
                self.upload_for_sharing()
            elif choice == '5' and self.session_id:
                self.list_and_download_shared_files()
            elif choice == '6' and self.session_id:
                self.download_server_public_file()
            elif choice == '7' and self.session_id and self.user_role == 'admin':
                self.auth_handler.make_file_public_admin()
            elif choice == 'L' and self.session_id:
                self.auth_handler.logout_user()
            elif choice == 'Q':
                print("Exiting client. Goodbye!")
                self._close_connection()
                break
            else:
                print("Invalid choice or you need to be logged in for that action. Please try again.")

def _get_ngrok_public_address():
    NGROK_API_URL = "http://127.0.0.1:4040/api/tunnels"
    try:
        response = requests.get(NGROK_API_URL)
        response.raise_for_status()
        tunnels_data = response.json()

        for tunnel in tunnels_data['tunnels']:
            if tunnel['proto'] == 'tcp':
                public_url = tunnel['public_url']
                parsed_url = urlparse(public_url)
                return parsed_url.hostname, parsed_url.port

        print("Error: No TCP tunnel found in ngrok API response.")
        return None, None

    except requests.exceptions.ConnectionError:
        print("Error: ngrok web interface not found. Is ngrok running and accessible on port 4040?")
        print("Please ensure ngrok is running in a separate terminal: `ngrok tcp 8080` (or your server's port)")
        return None, None
    except requests.exceptions.RequestException as e:
       print(f"Error querying ngrok API: {e}")
       return None, None

if __name__ == "__main__":
    SERVER_HOST = None
    SERVER_PORT = None

    print("Attempting to detect ngrok public address...")
    detected_host, detected_port = _get_ngrok_public_address()

    if detected_host and detected_port:
        SERVER_HOST = detected_host
        SERVER_PORT = detected_port
        print(f"Detected ngrok tunnel: {SERVER_HOST}:{SERVER_PORT}")
    else:
        print("Could not automatically detect ngrok tunnel. Falling back to default settings.")
        SERVER_HOST = "7.tcp.eu.ngrok.io"
        SERVER_PORT = 13769
        print(f"Using fallback server: {SERVER_HOST}:{SERVER_PORT}")
        if SERVER_HOST == "7.tcp.eu.ngrok.io":
            print(f"WARNING: You are using placeholder fallback host address: [{SERVER_HOST}:{SERVER_PORT}]"
                  "Please update them in client.py or ensure ngrok is running for auto-detection.")

    CLIENT_CERT_PATH = None
    CLIENT_KEY_PATH = None
    SERVER_CERT_PATH = "server.crt"

    if SERVER_HOST and SERVER_PORT and SERVER_HOST != "7.tcp.eu.ngrok.io":
        client = FileTransferClient(SERVER_HOST, SERVER_PORT,
                                    server_cert=SERVER_CERT_PATH,
                                    client_cert=CLIENT_CERT_PATH,
                                    client_key=CLIENT_KEY_PATH)
        client.run_client()
    else:
        print("\nClient cannot start without a valid server address. "
              "Please ensure ngrok is running or update fallback host/port.")