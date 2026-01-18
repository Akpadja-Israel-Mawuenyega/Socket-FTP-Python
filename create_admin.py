import os
import sys
import bcrypt
import configparser
import logging
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from user_management import DatabaseManager

def setup_logging():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def read_config(path='config.ini'):
    config = configparser.ConfigParser(interpolation=None)
    if not os.path.exists(path):
        logging.critical(f"Config file not found at {path}")
        sys.exit(1)
    config.read(path)
    return config

def main():
    load_dotenv()
    
    setup_logging()
    config = read_config()
    
    db_manager = DatabaseManager(config['DATABASE'])

    admin_username = input("Enter desired admin username: ")
    admin_password = input("Enter desired admin password: ")

    if db_manager.create_user(admin_username, admin_password, role='admin'):
        logging.info(f"Admin user '{admin_username}' created successfully!")
    else:
        logging.error(f"Failed to create admin user '{admin_username}'. It might already exist.")

if __name__ == "__main__":
    main()