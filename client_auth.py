import os
import tqdm
import sys
import logging
import socket

class ClientAuthHandler:
    def __init__(self, config):
        self.client_socket = None
        self.config = config
        self.LOGIN_SUCCESS_RESPONSE = config['RESPONSES']['LOGIN_SUCCESS']
        self.LOGIN_FAILED_RESPONSE = config['RESPONSES']['LOGIN_FAILED']
        self.REGISTER_SUCCESS_RESPONSE = config['RESPONSES']['REGISTER_SUCCESS']
        self.REGISTER_FAILED_RESPONSE = config['RESPONSES']['REGISTER_FAILED']
        self.LOGOUT_SUCCESS_RESPONSE = config['RESPONSES']['LOGOUT_SUCCESS']
        self.INVALID_SESSION_RESPONSE = config['RESPONSES']['INVALID_SESSION']
        self.PERMISSION_DENIED_RESPONSE = config['RESPONSES']['PERMISSION_DENIED']
        self.ERROR_RESPONSE = config['RESPONSES']['ERROR']
        self.separator = config['SERVER']['SEPARATOR']
        self.buffer_size = config['SERVER'].getint('BUFFER_SIZE')

    def set_socket(self, client_socket):
        self.client_socket = client_socket

    def _get_credentials(self):
        username = input("Enter username: ")
        password = input("Enter password: ")
        return username, password

    def login(self):
        try:
            username, password = self._get_credentials()
            command = f"{self.config['COMMANDS']['LOGIN']}{self.separator}{username}{self.separator}{password}"
            self.client_socket.sendall(command.encode())
            
            response = self.client_socket.recv(self.buffer_size).decode().strip()
            
            logging.debug(f"Received raw login response: '{response}'")

            parts = response.split(self.separator)
            status = parts[0]
            
            if status == self.LOGIN_SUCCESS_RESPONSE:
                if len(parts) >= 4:
                    session_id = parts[1]
                    username_res = parts[2]
                    role = parts[3]
                    logging.info(f"Login successful. Welcome, {username_res}")
                    return True, session_id, username_res, role
                else:
                    logging.error(f"Login success response malformed: {response}")
                    return False, None, None, None
            elif status == self.LOGIN_FAILED_RESPONSE:
                logging.warning("Login failed: Invalid username or password.")
                return False, None, None, None
            elif status == self.ERROR_RESPONSE:
                error_message = " ".join(parts[1:])
                logging.error(f"Server error during login: {error_message}")
                return False, None, None, None
            else:
                logging.error(f"Unknown response from server during login: {response}")
                return False, None, None, None
        
        except Exception as e:
            logging.error(f"An error occurred during login: {e}")
            return False, None, None, None

    def register(self):
        try:
            username, password = self._get_credentials()
            command = f"{self.config['COMMANDS']['REGISTER']}{self.separator}{username}{self.separator}{password}"
            self.client_socket.sendall(command.encode())
            
            response = self.client_socket.recv(self.buffer_size).decode().strip()
            
            parts = response.split(self.separator)
            status = parts[0]
            
            if status == self.REGISTER_SUCCESS_RESPONSE:
                logging.info("Registration successful. You can now log in.")
                return True
            elif status == self.REGISTER_FAILED_RESPONSE:
                logging.warning("Registration failed: Username may already exist or invalid input.")
                return False
            elif status == self.ERROR_RESPONSE:
                error_message = " ".join(parts[1:])
                logging.error(f"Server error during registration: {error_message}")
                return False
            else:
                logging.error(f"Unknown response from server during registration: {response}")
                return False
        except Exception as e:
            logging.error(f"An error occurred during registration: {e}")
            return False
            
    def logout(self, session_id):
        try:
            command = f"{self.config['COMMANDS']['LOGOUT']}{self.separator}{session_id}"
            self.client_socket.sendall(command.encode())
            
            response = self.client_socket.recv(self.buffer_size).decode().strip()
            
            if response == self.LOGOUT_SUCCESS_RESPONSE:
                logging.info("Logout successful.")
                return True
            elif response == self.INVALID_SESSION_RESPONSE:
                logging.warning("Logout failed: Invalid session ID.")
                return False
            else:
                logging.error(f"Unknown response from server during logout: {response}")
                return False
        except Exception as e:
            logging.error(f"An error occurred during logout: {e}")
            return False