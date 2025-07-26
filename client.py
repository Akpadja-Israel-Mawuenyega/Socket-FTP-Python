import socket
import tqdm
import os
import sys
import ssl
import logging
import requests
from urllib.parse import urlparse
import time
import configparser

from client_auth import ClientAuthHandler

def setup_logging(config):
    log_level_str = config['LOGGING'].get('LEVEL', 'INFO').upper()
    log_format = config['LOGGING'].get('FORMAT', '%(asctime)s - %(levelname)s - %(message)s')
    log_level = getattr(logging, log_level_str, logging.INFO)
    logging.basicConfig(level=log_level, format=log_format)

def read_config(path='config.ini'):
    config = configparser.ConfigParser(interpolation=None)
    if not os.path.exists(path):
        logging.critical(f"Config file not found at {path}")
        sys.exit(1)
    config.read(path)
    return config

class FileTransferClient:
    def __init__(self, host, port, config):
        self.host = host
        self.port = port
        self.config = config
        self.buffer_size = config['SERVER'].getint('BUFFER_SIZE')
        self.separator = config['SERVER']['SEPARATOR']
        self.downloads_base_dir = config['CLIENT']['DOWNLOAD_DIR']
        self.certfile = config['SERVER']['CERTFILE']
        self.secure_socket = None
        self.session_id = None
        self.username = None
        self.user_role = None

        logging.info(f"Download directory set to: {os.path.abspath(self.downloads_base_dir)}")
        
        self.auth_handler = ClientAuthHandler(self.config)

    def connect(self):
        try:
            context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=self.certfile)
            context.check_hostname = False
            self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.secure_socket = context.wrap_socket(self.s, server_hostname=self.host)
            self.secure_socket.connect((self.host, self.port))
            logging.info(f"Connected to {self.host}:{self.port} securely.")
            self.auth_handler.set_socket(self.secure_socket)
            return True
        except FileNotFoundError:
            logging.error(f"SSL certificate '{self.certfile}' not found.")
            return False
        except ssl.SSLError as e:
            logging.error(f"SSL error during connection: {e}")
            return False
        except socket.error as e:
            logging.error(f"Socket error during connection: {e}")
            return False
        except Exception as e:
            logging.error(f"An unexpected error occurred during connection: {e}")
            return False

    def start_interactive_session(self):
        try:
            if not self.connect():
                return
            while True:
                if not self.session_id:
                    choice = input(f"[{self.username}:{self.user_role}] > Enter '1' to login, '2' to register, 'q' to quit: ")
                    if choice == '1':
                        success, session_id, username, role = self.auth_handler.login()
                        if success:
                            self.session_id = session_id
                            self.username = username
                            self.user_role = role
                            self.downloads_dir = os.path.join(self.downloads_base_dir, self.username)
                            os.makedirs(self.downloads_dir, exist_ok=True)
                            logging.info(f"User-specific download directory set to: {os.path.abspath(self.downloads_dir)}")
                    elif choice == '2':
                        self.auth_handler.register()
                    elif choice.lower() == 'q':
                        break
                    else:
                        logging.warning("Invalid choice.")
                else:
                    command_raw = input(f"[{self.username}:{self.user_role}] > ")
                    command_parts = command_raw.split(self.separator)
                    command = command_parts[0]
                    args = command_parts[1:]
                    
                    if command.lower() == 'logout':
                        self.auth_handler.logout(self.session_id)
                        self.session_id = None
                        self.username = None
                        self.user_role = None
                    elif command.lower() == 'quit':
                        self.auth_handler.logout(self.session_id)
                        break
                    elif command.lower() == self.config['COMMANDS']['UPLOAD_PRIVATE'].lower():
                        if len(args) == 1:
                            self.handle_upload(args[0], private=True)
                        else:
                            logging.warning("Usage: UPLOAD_PRIVATE<SEP>filename")
                    elif command.lower() == self.config['COMMANDS']['UPLOAD_FOR_SHARING'].lower():
                        if len(args) == 1:
                            self.handle_upload(args[0], private=False)
                        else:
                            logging.warning("Usage: UPLOAD_FOR_SHARING<SEP>filename")
                    elif command.lower() == self.config['COMMANDS']['DOWNLOAD_PRIVATE'].lower():
                        if len(args) == 1:
                            self.handle_download_private(args[0])
                        else:
                            logging.warning("Usage: DOWNLOAD_PRIVATE<SEP>filename")
                    elif command.lower() == self.config['COMMANDS']['LIST_PRIVATE'].lower():
                        self.list_private_files()
                    elif command.lower() == self.config['COMMANDS']['DOWNLOAD_SERVER_PUBLIC'].lower():
                        if len(args) == 1:
                            self.handle_download_public(args[0])
                        else:
                            logging.warning("Usage: DOWNLOAD_SERVER_PUBLIC<SEP>filename")
                    elif command.lower() == self.config['COMMANDS']['LIST_SHARED'].lower():
                        self.list_shared_files()
                    elif command.lower() == self.config['COMMANDS']['DOWNLOAD_SHARED'].lower():
                        if len(args) == 1:
                            # This is the key change to prompt the user for the correct format
                            self.handle_download_shared(args[0])
                        else:
                            logging.warning("Usage: DOWNLOAD_SHARED<SEP>owner_username/filename")
                    elif command.lower() == self.config['COMMANDS']['MAKE_PUBLIC_ADMIN'].lower():
                        if self.user_role == 'admin':
                            if len(args) == 2:
                                self.make_public_admin(args[0], args[1])
                            else:
                                logging.warning("Usage: MAKE_PUBLIC_ADMIN<SEP>owner_username<SEP>filename")
                        else:
                            logging.warning("Permission denied.")
                    elif command.lower() == self.config['COMMANDS']['MAKE_PUBLIC_USER'].lower():
                        if self.user_role in ['user', 'admin']:
                            if len(args) == 1:
                                self.make_public_user(args[0])
                            else:
                                logging.warning("Usage: MAKE_PUBLIC_USER<SEP>filename")
                        else:
                            logging.warning("Permission denied.")
                    elif command.lower() == self.config['COMMANDS']['MAKE_SHARED_USER'].lower():
                        if self.user_role in ['user', 'admin']:
                            if len(args) == 1:
                                self.make_shared_user(args[0])
                            else:
                                logging.warning("Usage: MAKE_SHARED_USER<SEP>filename")
                        else:
                            logging.warning("Permission denied.")
                    else:
                        logging.warning("Unknown command.")        
        except KeyboardInterrupt:
            logging.info("Exiting interactive session.")
        finally:
            if self.secure_socket:
                self.secure_socket.close()
            logging.info("Disconnected from server.")

    def handle_upload(self, file_path, private):
        if not os.path.isfile(file_path):
            logging.error(f"File not found: {file_path}")
            return
        
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)

        command = f"{self.config['COMMANDS']['UPLOAD_PRIVATE'] if private else self.config['COMMANDS']['UPLOAD_FOR_SHARING']}{self.separator}{self.session_id}{self.separator}{file_name}{self.separator}{file_size}"
        self.secure_socket.sendall(command.encode())
        
        response = self.secure_socket.recv(self.buffer_size).decode().strip()
        parts = response.split(self.separator)
        status = parts[0]

        if status == self.config['RESPONSES']['READY_FOR_DATA']:
            logging.info("Server is ready for upload. Initiating transfer.")
            self._transfer_file(file_path)
        else:
            logging.error(f"Server refused upload: {response}")

    def handle_download_private(self, file_name):
        command = f"{self.config['COMMANDS']['DOWNLOAD_PRIVATE']}{self.separator}{self.session_id}{self.separator}{file_name}"
        self.secure_socket.sendall(command.encode())
        
        response = self.secure_socket.recv(self.buffer_size).decode().strip()
        parts = response.split(self.separator)
        status = parts[0]
        
        if status == self.config['RESPONSES']['DOWNLOAD_READY']:
            file_name_from_server = parts[1]
            file_size = int(parts[2])
            logging.info("Server is ready for download. Initiating transfer.")
            self._receive_file(file_name_from_server, file_size)
        elif status == self.config['RESPONSES']['FILE_NOT_FOUND']:
            logging.error(f"File '{file_name}' not found on server.")
        else:
            logging.error(f"Unexpected server response for download: {response}")

    def handle_download_public(self, file_name):
        command = f"{self.config['COMMANDS']['DOWNLOAD_SERVER_PUBLIC']}{self.separator}{file_name}"
        self.secure_socket.sendall(command.encode())
        
        response = self.secure_socket.recv(self.buffer_size).decode().strip()
        parts = response.split(self.separator)
        status = parts[0]
        
        if status == self.config['RESPONSES']['DOWNLOAD_READY']:
            file_name_from_server = parts[1]
            file_size = int(parts[2])
            logging.info("Server is ready for download. Initiating transfer.")
            self._receive_file(file_name_from_server, file_size)
        elif status == self.config['RESPONSES']['FILE_NOT_FOUND']:
            logging.error(f"File '{file_name}' not found on server.")
        else:
            logging.error(f"Unexpected server response for download: {response}")

    def handle_download_shared(self, owner_and_file_name):
        if not self.session_id:
            logging.warning("Please log in to download shared files.")
            return

        command = f"{self.config['COMMANDS']['DOWNLOAD_SHARED']}{self.separator}{self.session_id}{self.separator}{owner_and_file_name}"
        self.secure_socket.sendall(command.encode())

        response = self.secure_socket.recv(self.buffer_size).decode().strip()
        parts = response.split(self.separator)
        status = parts[0]
        
        if status == self.config['RESPONSES']['DOWNLOAD_READY']:
            file_name_from_server = parts[1]
            file_size = int(parts[2])
            logging.info("Server is ready for download. Initiating transfer.")
            self._receive_file(file_name_from_server, file_size)
        elif status == self.config['RESPONSES']['FILE_NOT_FOUND']:
            logging.error(f"File '{owner_and_file_name}' not found on server.")
        else:
            logging.error(f"Unexpected server response for download: {response}")

    def _transfer_file(self, file_path):
        try:
            file_size = os.path.getsize(file_path)
            file_name = os.path.basename(file_path)
            
            with open(file_path, "rb") as f:
                with tqdm.tqdm(total=file_size, unit="B", unit_scale=True, unit_divisor=1024, desc=f"Sending {file_name}") as progress:
                    while True:
                        bytes_read = f.read(self.buffer_size)
                        if not bytes_read:
                            break
                        self.secure_socket.sendall(bytes_read)
                        progress.update(len(bytes_read))
            
            final_response = self.secure_socket.recv(self.buffer_size).decode('utf-8').strip()
            logging.info(f"Server response after upload: {final_response}")
        except Exception as e:
            logging.error(f"Error during file upload data transfer: {e}", exc_info=True)

    def _receive_file(self, file_name, file_size):
        try:
            file_path = os.path.join(self.downloads_dir,file_name)
            
            with open(file_path, "wb") as f:
                with tqdm.tqdm(total=file_size, unit="B", unit_scale=True, unit_divisor=1024, desc=f"Receiving {file_name}") as progress:
                    bytes_received = 0
                    while bytes_received < file_size:
                        bytes_to_read = min(self.buffer_size, file_size - bytes_received)
                        bytes_read = self.secure_socket.recv(bytes_to_read)
                        if not bytes_read:
                            break
                        f.write(bytes_read)
                        bytes_received += len(bytes_read)
                        progress.update(len(bytes_read))
            
            logging.info(f"File '{file_name}' received successfully.")
            final_response = self.secure_socket.recv(self.buffer_size).decode('utf-8').strip()
            logging.info(f"Server response after download: {final_response}")
        except Exception as e:
            logging.error(f"Error during file download data transfer: {e}", exc_info=True)
            
    def list_private_files(self):
        command = f"{self.config['COMMANDS']['LIST_PRIVATE']}{self.separator}{self.session_id}"
        self.secure_socket.sendall(command.encode())

        response = self.secure_socket.recv(self.buffer_size).decode().strip()
        parts = response.split(self.separator)
        status = parts[0]

        if status == self.config['RESPONSES']['PRIVATE_LIST']:
            file_list = parts[1:]
            logging.info("--- Your Private Files ---")
            if not file_list:
                logging.info("No private files found.")
            for f in file_list:
                logging.info(f" - {f}")
        elif status == self.config['RESPONSES']['NO_FILES_PRIVATE']:
            logging.info("No private files found.")
        else:
            logging.error(f"Unexpected response from server: {response}")

    def list_shared_files(self):
        command = f"{self.config['COMMANDS']['LIST_SHARED']}{self.separator}{self.session_id}"
        self.secure_socket.sendall(command.encode())

        response = self.secure_socket.recv(self.buffer_size).decode().strip()
        parts = response.split(self.separator)
        status = parts[0]

        if status == self.config['RESPONSES']['SHARED_LIST']:
            file_list = parts[1:]
            logging.info("--- Shared Files ---")
            if not file_list:
                logging.info("No files are currently shared.")
            for f in file_list:
                logging.info(f" - {f}")
        elif status == self.config['RESPONSES']['NO_FILES_SHARED']:
            logging.info("No files are currently shared.")
        else:
            logging.error(f"Unexpected response from server: {response}")

    def make_public_admin(self, owner_username, file_name):
        if self.user_role != 'admin':
            logging.warning("Permission denied. You must be an admin to use this command.")
            return

        command = f"{self.config['COMMANDS']['MAKE_PUBLIC_ADMIN']}{self.separator}{self.session_id}{self.separator}{owner_username}{self.separator}{file_name}"
        self.secure_socket.sendall(command.encode())

        response = self.secure_socket.recv(self.buffer_size).decode().strip()
        logging.info(f"Server response: {response}")

    def make_public_user(self, file_name):
        if not self.session_id:
            logging.warning("Please log in to make a file public.")
            return
        
        command = f"{self.config['COMMANDS']['MAKE_PUBLIC_USER']}{self.separator}{self.session_id}{self.separator}{file_name}"
        self.secure_socket.sendall(command.encode())

        response = self.secure_socket.recv(self.buffer_size).decode().strip()
        logging.info(f"Server response: {response}")
        
    def make_shared_user(self, file_name):
        if not self.session_id:
            logging.warning("Please log in to make a file shared.")
            return
        
        command = f"{self.config['COMMANDS']['MAKE_SHARED_USER']}{self.separator}{self.session_id}{self.separator}{file_name}"
        self.secure_socket.sendall(command.encode())

        response = self.secure_socket.recv(self.buffer_size).decode().strip()
        logging.info(f"Server response: {response}")    
        
def main():
    config = read_config()
    setup_logging(config)
    try:
        host = config['CLIENT'].get('FALLBACK_SERVER_HOST', '127.0.0.1')
        port = config['CLIENT'].getint('FALLBACK_SERVER_PORT', 8080)
        
        if config['CLIENT'].getboolean('NGROK_AUTODETECT_ENABLED'):
            logging.info("Attempting to detect ngrok public address...")
            try:
                res = requests.get('http://127.0.0.1:4040/api/tunnels', timeout=2)
                tunnels = res.json()['tunnels']
                if tunnels:
                    tcp_tunnels = [t for t in tunnels if t['proto'] == 'tcp']
                    if tcp_tunnels:
                        public_url = tcp_tunnels[0]['public_url']
                        parsed_url = urlparse(public_url)
                        host = parsed_url.hostname
                        port = parsed_url.port
                        logging.info(f"Found ngrok tunnel: {public_url}. Using host: {host}, port: {port}")
                    else:
                        logging.error("ngrok web interface found, but no TCP tunnels are active.")
                        logging.info(f"Using fallback server: {host}:{port}")
                else:
                    logging.error("ngrok web interface found, but no tunnels are active. Is ngrok running and a tunnel configured?")
                    logging.info(f"Using fallback server: {host}:{port}")
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                logging.error("ngrok web interface not found. Is ngrok running and accessible on port 4040?")
                logging.error(f"Please ensure ngrok is running in a separate terminal: `ngrok tcp <SERVER_PORT_FROM_CONFIG>`")
                logging.error("Could not automatically detect ngrok tunnel. Falling back to default settings.")
                logging.info(f"Using fallback server: {host}:{port}")
            except Exception as e:
                logging.error(f"An unexpected error occurred during ngrok detection: {e}")
                logging.info(f"Using fallback server: {host}:{port}")
        else:
            logging.info(f"Using fallback server: {host}:{port}")

        client = FileTransferClient(host=host, port=port, config=config)
        client.start_interactive_session()
    except Exception as e:
        logging.critical(f"Application error: {e}")
        
if __name__ == "__main__":
    main()