import threading
import socket
import tqdm
import os
import sys

class ClientHandler(threading.Thread):
    """
    A thread class to handle individual client connections for file transfer.
    Now supports uploads to a private folder, uploads to a shared folder,
    listing shared files, and downloading shared files.
    """
    def __init__(self, client_socket: socket.socket, address: tuple, server_config: dict):
        super().__init__()
        self.client_socket = client_socket
        self.address = address
        self.buffer_size = server_config['buffer_size']
        self.separator = server_config['separator']
        self.upload_dir = server_config['upload_dir']          # For private uploads
        self.shared_files_dir = server_config['shared_files_dir'] # For server's public files
        self.shared_uploads_dir = server_config['shared_uploads_dir'] # New: For client-shared files
        
        # Command constants from server config
        self.UPLOAD_PRIVATE_COMMAND = server_config['UPLOAD_PRIVATE_COMMAND']
        self.DOWNLOAD_SERVER_PUBLIC_COMMAND = server_config['DOWNLOAD_SERVER_PUBLIC_COMMAND']
        self.UPLOAD_FOR_SHARING_COMMAND = server_config['UPLOAD_FOR_SHARING_COMMAND'] # New
        self.LIST_SHARED_COMMAND = server_config['LIST_SHARED_COMMAND']             # New
        self.DOWNLOAD_SHARED_COMMAND = server_config['DOWNLOAD_SHARED_COMMAND']     # New
        
        self.DOWNLOAD_START_RESPONSE = server_config['DOWNLOAD_START_RESPONSE']
        self.FILE_NOT_FOUND_RESPONSE = server_config['FILE_NOT_FOUND_RESPONSE']
        self.SHARED_LIST_RESPONSE = server_config['SHARED_LIST_RESPONSE']           # New
        self.NO_FILES_SHARED_RESPONSE = server_config['NO_FILES_SHARED_RESPONSE']   # New

        self.daemon = True 

    def run(self):
        try:
            initial_data = self.client_socket.recv(self.buffer_size).decode('latin-1')
            parts = initial_data.split(self.separator, 2)

            command = parts[0]

            if command == self.UPLOAD_PRIVATE_COMMAND:
                filename_encoded = parts[1]
                filesize_str = parts[2]
                
                filename = filename_encoded.encode('latin-1').decode('utf-8')
                filesize = int(filesize_str)

                filepath = os.path.join(self.upload_dir, os.path.basename(filename))
                print(f"[Client {self.address}] Receiving private upload '{filename}' ({filesize} bytes)...")
                self._receive_file_data(self.client_socket, filepath, filesize, filename)

            elif command == self.DOWNLOAD_SERVER_PUBLIC_COMMAND:
                requested_filename = parts[1]
                print(f"[Client {self.address}] Requested server public file '{requested_filename}' for download.")
                self._serve_file_to_client(self.client_socket, requested_filename, self.shared_files_dir)

            elif command == self.UPLOAD_FOR_SHARING_COMMAND: # Handle new upload for sharing
                filename_encoded = parts[1]
                filesize_str = parts[2]
                
                filename = filename_encoded.encode('latin-1').decode('utf-8')
                filesize = int(filesize_str)

                filepath = os.path.join(self.shared_uploads_dir, os.path.basename(filename))
                print(f"[Client {self.address}] Receiving shared upload '{filename}' ({filesize} bytes)...")
                self._receive_file_data(self.client_socket, filepath, filesize, filename)

            elif command == self.LIST_SHARED_COMMAND: # Handle new list shared files
                print(f"[Client {self.address}] Requested list of shared files.")
                self._handle_list_shared_files(self.client_socket)

            elif command == self.DOWNLOAD_SHARED_COMMAND: # Handle new download shared file
                requested_filename = parts[1]
                print(f"[Client {self.address}] Requested shared file '{requested_filename}' for download.")
                self._serve_file_to_client(self.client_socket, requested_filename, self.shared_uploads_dir)

            else:
                print(f"[Client {self.address}] Unknown command received: {command}")
                self.client_socket.sendall("UNKNOWN_COMMAND".encode('latin-1'))

        except ConnectionResetError:
            print(f"[Client {self.address}] Disconnected unexpectedly.")
        except BrokenPipeError:
            print(f"[Client {self.address}] Broken pipe. Connection lost.")
        except ValueError:
            print(f"[Client {self.address}] Error: Invalid data format received. Check client protocol.")
        except Exception as e:
            print(f"[Client {self.address}] An unexpected error occurred: {e}")
        finally:
            print(f"[Client {self.address}] Closing connection.")
            self.client_socket.close()

    def _receive_file_data(self, client_socket: socket.socket, filepath: str, filesize: int, display_filename: str):
        """Helper method to receive file data into a specified path."""
        try:
            # Use 'leave=True' for server-side tqdm if you want logs to stay
            # Use 'leave=False' to clear the bar after completion
            progress = tqdm.tqdm(range(filesize), f"Receiving {os.path.basename(display_filename)}", unit="B", unit_scale=True, unit_divisor=1024, leave=False)
            with open(filepath, "wb") as f:
                bytes_received = 0
                while bytes_received < filesize:
                    bytes_read = client_socket.recv(self.buffer_size)
                    if not bytes_read:
                        break
                    f.write(bytes_read)
                    bytes_received += len(bytes_read)
                    progress.update(len(bytes_read))
            progress.close()

            if bytes_received == filesize:
                print(f"[Client {self.address}] Successfully received '{display_filename}' and saved to '{filepath}'.")
            else:
                print(f"[Client {self.address}] Warning: Received {bytes_received} bytes, expected {filesize} bytes for '{display_filename}'. File might be incomplete.")

        except FileNotFoundError:
            print(f"[Client {self.address}] Error: Could not open file for writing at '{filepath}'. Check permissions.")
        except OSError as e:
            print(f"[Client {self.address}] An OS error occurred while writing file: {e}")
        except Exception as e:
            print(f"[Client {self.address}] An error occurred during file data reception: {e}")

    def _serve_file_to_client(self, client_socket: socket.socket, requested_filename: str, source_directory: str):
        """Helper method to send a requested file from a specified source directory to the client."""
        filepath = os.path.join(source_directory, os.path.basename(requested_filename))

        if not os.path.exists(filepath) or not os.path.isfile(filepath):
            print(f"[Client {self.address}] Requested '{requested_filename}' from '{source_directory}' but it was not found.")
            response = f"{self.FILE_NOT_FOUND_RESPONSE}{self.separator}{requested_filename}".encode('latin-1')
            client_socket.sendall(response)
            return

        try:
            filesize = os.path.getsize(filepath)
            
            encoded_filename = os.path.basename(requested_filename).encode('utf-8')
            response = f"{self.DOWNLOAD_START_RESPONSE}{self.separator}{encoded_filename.decode('latin-1')}{self.separator}{filesize}".encode('latin-1')
            client_socket.sendall(response)

            print(f"[Client {self.address}] Serving '{requested_filename}' ({filesize} bytes) from '{source_directory}'...")
            
            progress = tqdm.tqdm(range(filesize), f"Serving {os.path.basename(requested_filename)}", unit="B", unit_scale=True, unit_divisor=1024, leave=False)
            with open(filepath, "rb") as f:
                while True:
                    bytes_read = f.read(self.buffer_size)
                    if not bytes_read:
                        break
                    client_socket.sendall(bytes_read)
                    progress.update(len(bytes_read))
            progress.close()
            print(f"[Client {self.address}] Successfully served '{requested_filename}'.")

        except FileNotFoundError: # Should be caught by exists check, but good fallback
            print(f"[Client {self.address}] Error: File '{requested_filename}' disappeared during serving.")
            client_socket.sendall(f"{self.FILE_NOT_FOUND_RESPONSE}{self.separator}{requested_filename}".encode('latin-1'))
        except OSError as e:
            print(f"[Client {self.address}] An OS error occurred while serving file: {e}")
        except Exception as e:
            print(f"[Client {self.address}] An unexpected error occurred during file serving: {e}")

    def _handle_list_shared_files(self, client_socket: socket.socket):
        """Helper method to list files in the shared_uploads directory."""
        try:
            shared_files = [f for f in os.listdir(self.shared_uploads_dir) if os.path.isfile(os.path.join(self.shared_uploads_dir, f))]
            
            if not shared_files:
                response = self.NO_FILES_SHARED_RESPONSE.encode('latin-1')
                client_socket.sendall(response)
                print(f"[Client {self.address}] No shared files to list.")
                return

            # Join file names with a specific sub-separator for the list
            # Using a character unlikely to be in filenames, e.g., '|||'
            files_list_str = "|||".join(shared_files)
            
            response = f"{self.SHARED_LIST_RESPONSE}{self.separator}{files_list_str}".encode('latin-1')
            client_socket.sendall(response)
            print(f"[Client {self.address}] Sent list of shared files.")

        except Exception as e:
            print(f"[Client {self.address}] Error listing shared files: {e}")
            client_socket.sendall("SERVER_ERROR".encode('latin-1')) # Generic error response
