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

def read_config(path='client_config.ini'):
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
        self.buffer_size = config['CONNECTION'].getint('BUFFER_SIZE')
        self.separator = config['CONNECTION']['SEPARATOR']
        self.downloads_base_dir = config['SETTINGS']['DOWNLOAD_DIR']
        self.certfile = config['CONNECTION']['CERTFILE']
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
                    choice = input("Enter '1' to login, '2' to register, 'q' to quit: ")
                    
                    if choice == '1':
                        u = input("Enter your username (Must be unique): ")
                        p = input("Enter password: ")
                        
                        success, session_id, username, role = self.auth_handler.login(u, p)
                        
                        if success:
                            self.session_id = session_id
                            self.username = username
                            self.user_role = role
                            self.downloads_dir = os.path.join(self.downloads_base_dir, self.username)
                            os.makedirs(self.downloads_dir, exist_ok=True)
                            logging.info(f"User-specific download directory set to: {os.path.abspath(self.downloads_dir)}")

                    elif choice == '2':
                        u = input("Choose a username (Must be unique): ")
                        p = input("Choose a password: ")
                        
                        self.auth_handler.register(u, p)
                    elif choice.lower() == 'q':
                        break
                    else:
                        logging.warning("Invalid choice.")
                else:
                    user_input = input(f"[{self.username}] > ").strip()
                    if not user_input: continue
                    
                    parts = user_input.split(self.separator)
                    cmd_raw = parts[0].upper()
                    args = parts[1:]

                    if "LIST_" in cmd_raw:
                        self.handle_list(cmd_raw)

                    elif "DOWNLOAD" in cmd_raw:
                        if args: self.handle_file_download(args[0], cmd_raw)
                        else: print("Usage: DOWNLOAD_TYPE<SEPARATOR>FILE_ID")

                    elif "MAKE_" in cmd_raw:
                        if len(args) >= 1:
                            target = args[1] if len(args) > 1 else None
                            self.handle_file_action(cmd_raw, args[0], target)
                        else: print("Usage: MAKE_...<SEPARATOR>FILE_ID<SEPARATOR>[TARGET_USER]")

                    elif "DELETE" in cmd_raw:
                        if args: self.handle_file_action(cmd_raw, args[0])
                        else: print("Usage: DELETE<SEPARATOR>FILE_ID")

                    elif "UPLOAD" in cmd_raw:
                        if len(args) >= 1:
                            file_path = args[0]
                            recipient = args[1] if len(args) > 1 else None
                            
                            self.handle_file_upload(cmd_raw, file_path, recipient)
                        else:
                            print("Usage: UPLOAD_<TYPE><SEPARATOR>local_path<SEPARATOR>[recipient_username]")

                    elif cmd_raw == "LOGOUT":
                        if self.auth_handler.logout(self.session_id):
                            self.session_id = None
                            self.username = None
                            self.user_role = None
                            logging.info("Logged out successfully.")
                        else:
                            logging.error("Logout failed on server side.")
                    elif cmd_raw == "QUIT":
                        if self.session_id:
                            self.auth_handler.logout(self.session_id)
                        break
        except Exception as e:
            logging.error(f"An error during user session: {e}")        
                            
    def send_command(self, cmd_name, *args):
        """
        One method to rule them all. 
        Automatically injects session_id and sends any number of arguments.
        """
        cmd_value = self.config['COMMANDS'].get(cmd_name, cmd_name)
        request = self.separator.join([cmd_value, str(self.session_id)] + list(args))
        
        self.secure_socket.sendall(request.encode('utf-8'))
        response = self.secure_socket.recv(self.buffer_size).decode('utf-8').strip()
        return response.split(self.separator)

    def handle_list(self, cmd_name):
        parts = self.send_command(cmd_name)
        status = parts[0]

        if status == self.config['RESPONSES']['LIST_SUCCESS']:
            print(f"\n--- {cmd_name.replace('_', ' ')} ---")
            file_entries = parts[1:]
            for i in range(0, len(file_entries), 2):
                f_id = file_entries[i]
                f_name = file_entries[i+1] if (i+1) < len(file_entries) else "Unknown"
                print(f" [{f_id}] {f_name}")
            print("-" * 25)

        elif status.startswith("NO_FILES") or status == "LIST_EMPTY":
            print(f"\nInfo: {status.replace('_', ' ').title()}")
            logging.info(f"Category '{cmd_name}' is currently empty.")

        else:
            logging.error(f"Unexpected Server Response: {status}")
    
    def transfer_file(self, file_path):
        """
        Reads a local file and streams bytes to the server.
        Uses tqdm for a visual progress bar in the CLI.
        """
        try:
            file_size = os.path.getsize(file_path)
            file_name = os.path.basename(file_path)
            
            with open(file_path, "rb") as f:
                with tqdm.tqdm(total=file_size, unit="B", unit_scale=True, 
                            unit_divisor=1024, desc=f"Uploading {file_name}") as progress:
                    
                    while True:
                        bytes_read = f.read(self.buffer_size)
                        if not bytes_read:
                            break
                        
                        self.secure_socket.sendall(bytes_read)
                        
                        progress.update(len(bytes_read))
            
            final_response = self.secure_socket.recv(self.buffer_size).decode('utf-8').strip()

            if final_response == "UPLOAD_SUCCESS":
                logging.info("File upload verified and saved successfully!")
            else:
                logging.error(f"Server reported an issue after transfer: {final_response}")
            
        except Exception as e:
            logging.error(f"Error during file transfer: {e}", exc_info=True)
    
    def handle_file_upload(self, cmd_key, file_path, recipient_username=None):
        if not os.path.isfile(file_path):
            logging.error(f"File not found: {file_path}")
            return

        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)

        upload_args = [file_name, str(file_size)]
        if recipient_username:
            upload_args.insert(0, recipient_username)

        parts = self.send_command(cmd_key, *upload_args)
        status = parts[0]

        if status == self.config['RESPONSES']['READY_FOR_DATA']:
            logging.info(f"Server ready. Transferring {file_name}...")
            self.transfer_file(file_path)
        else:
            logging.error(f"Server refused upload: {status}")        

    def receive_file(self, full_file_path, file_size):
        try:
            with open(full_file_path, "wb") as f:
                with tqdm.tqdm(total=file_size, unit="B", unit_scale=True, 
                            desc=f"Downloading {os.path.basename(full_file_path)}") as progress:
                    bytes_received = 0
                    while bytes_received < file_size:
                        bytes_to_read = min(self.buffer_size, file_size - bytes_received)
                        chunk = self.secure_socket.recv(bytes_to_read)
                        if not chunk: break
                        f.write(chunk)
                        bytes_received += len(chunk)
                        progress.update(len(chunk))
            
            return True
        except Exception as e:
            logging.error(f"Download failed: {e}")
            if os.path.exists(full_file_path): os.remove(full_file_path)
            return False
        
    def handle_file_download(self, file_id, cmd_raw):
        parts = self.send_command(cmd_raw, file_id)
        status = parts[0]

        if status == self.config['RESPONSES']['DOWNLOAD_READY']:
            filename, size = parts[1], int(parts[2])
            local_path = os.path.join(self.downloads_dir, filename)
            self.receive_file(local_path, size)
        else:
            logging.error(f"Download failed: {status}")

    def handle_file_action(self, cmd_name, file_id, target=None):
        args = [file_id]
        if target: args.append(target)
        
        parts = self.send_command(cmd_name, *args)
        print(f"Server: {parts[0]}")      
        
def main():
    config = read_config()
    setup_logging(config)
    try:
        host = config['CONNECTION'].get('FALLBACK_SERVER_HOST', '127.0.0.1')
        port = config['CONNECTION'].getint('FALLBACK_SERVER_PORT', 8080)
        
        if config['CONNECTION'].getboolean('NGROK_AUTODETECT_ENABLED'):
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