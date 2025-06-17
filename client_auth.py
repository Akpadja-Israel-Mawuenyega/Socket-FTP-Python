import os
import tqdm
import sys

class ClientAuthHandler:
    def __init__(self, client_instance):
        self.client = client_instance
        self.separator = client_instance.separator

        # Use client's command/response constants for consistency
        self.REGISTER_COMMAND = client_instance.REGISTER_COMMAND
        self.LOGIN_COMMAND = client_instance.LOGIN_COMMAND
        self.LOGOUT_COMMAND = client_instance.LOGOUT_COMMAND
        self.MAKE_PUBLIC_ADMIN_COMMAND = client_instance.MAKE_PUBLIC_ADMIN_COMMAND

        self.REGISTER_SUCCESS_RESPONSE = client_instance.REGISTER_SUCCESS_RESPONSE
        self.REGISTER_FAILED_RESPONSE = client_instance.REGISTER_FAILED_RESPONSE
        self.LOGIN_SUCCESS_RESPONSE = client_instance.LOGIN_SUCCESS_RESPONSE
        self.LOGIN_FAILED_RESPONSE = client_instance.LOGIN_FAILED_RESPONSE
        self.LOGOUT_SUCCESS_RESPONSE = client_instance.LOGOUT_SUCCESS_RESPONSE
        self.AUTHENTICATION_REQUIRED_RESPONSE = client_instance.AUTHENTICATION_REQUIRED_RESPONSE
        self.PERMISSION_DENIED_RESPONSE = client_instance.PERMISSION_DENIED_RESPONSE
        self.ADMIN_FILE_MAKE_PUBLIC_SUCCESS = client_instance.ADMIN_FILE_MAKE_PUBLIC_SUCCESS
        self.ADMIN_FILE_MAKE_PUBLIC_FAILED = client_instance.ADMIN_FILE_MAKE_PUBLIC_FAILED
        self.INVALID_SESSION_RESPONSE = client_instance.INVALID_SESSION_RESPONSE


    def register_user(self):
        if self.client.session_id:
            print("You are already logged in. Please log out first to register a new user.")
            return
        username = input("Enter desired username: ")
        password = input("Enter desired password: ")
        command_str = f"{self.REGISTER_COMMAND}{self.separator}{username}{self.separator}{password}"
        response = self.client._send_command(command_str) # Use client's internal send method

        if response == self.REGISTER_SUCCESS_RESPONSE:
            print(f"User '{username}' registered successfully!")
        elif response.startswith(self.REGISTER_FAILED_RESPONSE):
            print(f"Registration failed: {response.split(self.separator, 1)[1]}")
        else:
            print(f"Unexpected response during registration: {response}")

    def login_user(self):
        if self.client.session_id:
            print(f"You are already logged in as {self.client.username} ({self.client.user_role}).")
            return
        username = input("Enter username: ")
        password = input("Enter password: ")
        command_str = f"{self.LOGIN_COMMAND}{self.separator}{username}{self.separator}{password}"
        response = self.client._send_command(command_str)

        if response.startswith(self.LOGIN_SUCCESS_RESPONSE):
            parts = response.split(self.separator, 2)
            if len(parts) == 3:
                self.client.session_id = parts[1]
                self.client.user_role = parts[2]
                self.client.username = username
                print(f"Logged in successfully as {self.client.username} ({self.client.user_role})!")
            else:
                print(f"Login failed: Malformed success response from server: {response}")
        elif response.startswith(self.LOGIN_FAILED_RESPONSE):
            print(f"Login failed: {response.split(self.separator, 1)[1]}")
        else:
            print(f"Unexpected response during login: {response}")

    def logout_user(self):
        if not self.client.session_id:
            print("You are not logged in.")
            return
        command_str = f"{self.LOGOUT_COMMAND}{self.separator}{self.client.session_id}"
        response = self.client._send_command(command_str)

        if response == self.LOGOUT_SUCCESS_RESPONSE:
            print(f"Logged out user {self.client.username}.")
            self.client.session_id = None
            self.client.username = None
            self.client.user_role = None
        elif response.startswith("ERROR"):
            print(f"Error during logout: {response}")
            # Even if server reports error, clear client side session for safety
            self.client.session_id = None
            self.client.username = None
            self.client.user_role = None
        else:
            print(f"Unexpected response during logout: {response}")
            self.client.session_id = None
            self.client.username = None
            self.client.user_role = None

    def make_file_public_admin(self):
        if not self.client.session_id:
            print("You must be logged in to use this command.")
            return
        if self.client.user_role != 'admin':
            print("Permission denied: Only admin users can make files public.")
            return
        
        full_path_on_server = input("Enter the FULL PATH of the file on the SERVER to make public: ")
        
        command_str = f"{self.MAKE_PUBLIC_ADMIN_COMMAND}{self.separator}{full_path_on_server}"
        response = self.client._send_command(command_str)

        if response.startswith(self.ADMIN_FILE_MAKE_PUBLIC_SUCCESS):
            parts = response.split(self.separator, 1)
            print(f"Successfully made '{parts[1] if len(parts) > 1 else 'file'}' public!")
        elif response.startswith(self.ADMIN_FILE_MAKE_PUBLIC_FAILED):
            parts = response.split(self.separator, 1)
            print(f"Failed to make file public: {parts[1] if len(parts) > 1 else 'Unknown reason'}")
        elif response.startswith(self.PERMISSION_DENIED_RESPONSE):
            print("Permission denied: You do not have admin rights.")
        elif response.startswith(self.INVALID_SESSION_RESPONSE):
            print("Your session is invalid or expired. Please log in again.")
            self.client.session_id = None
            self.client.username = None
            self.client.user_role = None
        elif response.startswith("ERROR"):
            print(f"An error occurred: {response}")
        else:
            print(f"Unexpected response from server: {response}")