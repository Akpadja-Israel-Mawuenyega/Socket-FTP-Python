import socket
import ssl
import os
import sys
import threading
import configparser
import logging
from dotenv import load_dotenv

from thread_functions import ClientHandler
from server_auth import ServerAuthHandler
from user_management import DatabaseManager

def setup_logging(config):
    # setup logging levels and file
    log_level_str = config['LOGGING'].get('LEVEL', 'INFO').upper()
    log_format = config['LOGGING'].get('FORMAT', '%(asctime)s - %(levelname)s - %(message)s')
    log_level = getattr(logging, log_level_str, logging.INFO)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    formatter = logging.Formatter(log_format)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    log_file = config['LOGGING'].get('SERVER_LOG_FILE')
    if log_file:
        try:
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
            logging.info(f"Logging configured to write to file: {log_file}")
        except Exception as e:
            logging.error(f"Failed to set up file logging: {e}")

def read_config(path='server_config.ini'):
    # read configs
    config = configparser.ConfigParser(interpolation=None)
    if not os.path.exists(path):
        logging.critical(f"Config file not found at {path}")
        sys.exit(1)
    config.read(path)
    return config

def create_server_directories(server_config):
    # Creates the necessary file transfer directories if they do not exist.
    try:
        upload_dir = server_config['UPLOAD_DIR']
        public_files_dir = server_config['PUBLIC_FILES_DIR']
        shared_uploads_dir = server_config['SHARED_UPLOADS_DIR']

        os.makedirs(upload_dir, exist_ok=True)
        os.makedirs(public_files_dir, exist_ok=True)
        os.makedirs(shared_uploads_dir, exist_ok=True)
        logging.info("All server directories ensured to exist.")
    except Exception as e:
        logging.critical(f"Error creating server directories: {e}", exc_info=True)
        sys.exit(1)

def main():
    # main executed function
    load_dotenv()
    
    config = read_config()
    setup_logging(config)
    
    db_config = config['DATABASE']
    server_config = config['SERVER']
    
    create_server_directories(server_config)

    try:
        db_manager = DatabaseManager(db_config)
        db_manager.create_user_table_if_not_exists()
        db_manager.create_files_table_if_not_exists()
        auth_handler = ServerAuthHandler(db_manager, config)
    except Exception as e:
        logging.critical(f"Error initializing database or auth handler: {e}", exc_info=True)
        sys.exit(1)

    host = server_config['HOST']
    port = server_config.getint('PORT')
    certfile = server_config['CERTFILE']
    keyfile = server_config['KEYFILE']

    if not os.path.exists(certfile) or not os.path.exists(keyfile):
        logging.critical(f"SSL certificate or key file not found: {certfile}, {keyfile}")
        sys.exit(1)

    try:
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(certfile=certfile, keyfile=keyfile)

        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.bind((host, port))
        server_socket.listen(5)
        logging.info(f"Listening on {host}:{port}")

        with context.wrap_socket(server_socket, server_side=True) as secure_socket:
            while True:
                try:
                    client_socket, address = secure_socket.accept()
                    logging.info(f"[+] Accepted connection from {address[0]}:{address[1]}")
                    client_thread = ClientHandler(client_socket, address, config, auth_handler, db_manager)
                    client_thread.start()
                except ssl.SSLError as e:
                    logging.error(f"SSL error during client connection: {e}")
                except Exception as e:
                    logging.error(f"An unexpected error occurred: {e}", exc_info=True)

    except Exception as e:
        logging.critical(f"Server application error: {e}", exc_info=True)
    finally:
        if 'db_manager' in locals():
            db_manager.close_pool()
        if 'server_socket' in locals() and server_socket:
            server_socket.close()

if __name__ == "__main__":
    main()