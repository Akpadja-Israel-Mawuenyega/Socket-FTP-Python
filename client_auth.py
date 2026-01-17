import logging

class ClientAuthHandler:
    def __init__(self, config):
        self.client_socket = None
        self.config = config
        self.separator = config['SERVER']['SEPARATOR']
        self.buffer_size = config['SERVER'].getint('BUFFER_SIZE')
        
        self.responses = config['RESPONSES']
        self.cmds = config['COMMANDS']

    def set_socket(self, client_socket):
        self.client_socket = client_socket

    def _send_and_receive(self, command_type, *args):
        """Helper to format commands and get server response."""
        try:
            payload = self.separator.join([command_type] + list(args))
            self.client_socket.sendall(payload.encode())
            
            response = self.client_socket.recv(self.buffer_size).decode().strip()
            return response.split(self.separator)
        except Exception as e:
            logging.error(f"Network error during {command_type}: {e}")
            return [self.responses['ERROR'], str(e)]

    def login(self, username, password):
        """Logic only: No 'input()' calls here."""
        parts = self._send_and_receive(self.cmds['LOGIN'], username, password)
        status = parts[0]

        if status == self.responses['LOGIN_SUCCESS']:
            if len(parts) >= 4:
                # Returns: (True, session_id, username, role)
                logging.info(f"Login successful. Welcome, {parts[2]}")
                return True, parts[1], parts[2], parts[3]
            
        elif status == self.responses['LOGIN_FAILED']:
            logging.warning("Login failed: Invalid credentials.")
        elif status == self.responses['ERROR']:
            logging.error(f"Server error: {' '.join(parts[1:])}")
            
        return False, None, None, None

    def register(self, username, password):
        """Logic only: No 'input()' calls here."""
        parts = self._send_and_receive(self.cmds['REGISTER'], username, password)
        
        if parts[0] == self.responses['REGISTER_SUCCESS']:
            logging.info("Registration successful.")
            return True
        
        logging.warning(f"Registration failed: {parts[0]}")
        return False

    def logout(self, session_id):
        parts = self._send_and_receive(self.cmds['LOGOUT'], session_id)
        if parts[0] == self.responses['LOGOUT_SUCCESS']:
            return True
        return False