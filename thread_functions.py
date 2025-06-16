import threading
import socket
import tqdm
import os
import sys
import ssl

class ClientHandler(threading.Thread):
    # A thread class to handle individual client connections for file transfer.
    # Supports uploads to a private folder, uploads to a shared folder,
    # listing shared files, and downloading shared files.

    # Class initializer method
    def __init__(self, client_socket: socket.socket, address: tuple, server_config: dict):
        super().__init__()
        self.client_socket = client_socket # This socket is ALREADY SSL-wrapped by server.py
        self.address = address
        self.buffer_size = server_config['buffer_size']
        self.separator = server_config['separator']
        self.upload_dir = server_config['upload_dir']          # For private uploads
        self.shared_files_dir = server_config['shared_files_dir'] # For server's public files
        self.shared_uploads_dir = server_config['shared_uploads_dir']   # For client-shared files

        # Command constants from server config
        self.UPLOAD_PRIVATE_COMMAND = server_config['UPLOAD_PRIVATE_COMMAND']
        self.DOWNLOAD_SERVER_PUBLIC_COMMAND = server_config['DOWNLOAD_SERVER_PUBLIC_COMMAND']
        self.UPLOAD_FOR_SHARING_COMMAND = server_config['UPLOAD_FOR_SHARING_COMMAND']
        self.LIST_SHARED_COMMAND = server_config['LIST_SHARED_COMMAND']
        self.DOWNLOAD_SHARED_COMMAND = server_config['DOWNLOAD_SHARED_COMMAND']

        self.DOWNLOAD_START_RESPONSE = server_config['DOWNLOAD_START_RESPONSE']
        self.FILE_NOT_FOUND_RESPONSE = server_config['FILE_NOT_FOUND_RESPONSE']
        self.SHARED_LIST_RESPONSE = server_config['SHARED_LIST_RESPONSE']
        self.NO_FILES_SHARED_RESPONSE = server_config['NO_FILES_SHARED_RESPONSE']

        self.daemon = True

    def run(self):
        try:
            print(f"[{self.address}] Handler started. Waiting for command...")
            # Receive the initial command from the client
            initial_data = self.client_socket.recv(self.buffer_size).decode('utf-8')
            if not initial_data:
                print(f"[{self.address}] Client disconnected before sending command.")
                return # Exit thread if client disconnects immediately

            print(f"[{self.address}] Received command: {initial_data}")
            parts = initial_data.split(self.separator, 2) # Split into command, filename, filesize

            command = parts[0]

            if command == self.UPLOAD_PRIVATE_COMMAND or \
               command == self.UPLOAD_FOR_SHARING_COMMAND:
                if len(parts) < 3:
                    print(f"[{self.address}] Malformed UPLOAD command: {initial_data}")
                    self.client_socket.sendall(b"ERROR: Malformed UPLOAD command")
                    return

                filename_encoded = parts[1]
                filesize_str = parts[2]

                filename = filename_encoded.encode('utf-8').decode('utf-8')
                filesize = int(filesize_str)

                # Determine target directory
                target_dir = self.upload_dir if command == self.UPLOAD_PRIVATE_COMMAND else self.shared_uploads_dir
                filepath = os.path.join(target_dir, os.path.basename(filename))

                print(f"[{self.address}] Preparing to receive '{filename}' ({filesize} bytes) into '{target_dir}'...")

                # --- Server sends ACK: Ready for file data ---
                self.client_socket.sendall(b"READY_FOR_FILE_DATA")
                print(f"[{self.address}] Sent 'READY_FOR_FILE_DATA' acknowledgment.")
                # -----------------------------------------------

                received_ok = self._receive_file_data(self.client_socket, filepath, filesize, filename)

                if received_ok:
                    self.client_socket.sendall(b"UPLOAD_COMPLETE")
                    print(f"[{self.address}] Sent 'UPLOAD_COMPLETE' status.")
                else:
                    self.client_socket.sendall(b"UPLOAD_INCOMPLETE")
                    print(f"[{self.address}] Sent 'UPLOAD_INCOMPLETE' status.")

            elif command == self.LIST_SHARED_COMMAND: # Handle new list shared files
                print(f"[{self.address}] Client requested list of shared files.")
                self._handle_list_shared_files(self.client_socket)

            elif command == self.DOWNLOAD_SERVER_PUBLIC_COMMAND or \
                 command == self.DOWNLOAD_SHARED_COMMAND: # Handle new download shared file
                if len(parts) < 2:
                    print(f"[{self.address}] Malformed DOWNLOAD command: {initial_data}")
                    self.client_socket.sendall(b"ERROR: Malformed DOWNLOAD command")
                    return

                requested_filename = parts[1]
                source_dir = self.shared_files_dir if command == self.DOWNLOAD_SERVER_PUBLIC_COMMAND else self.shared_uploads_dir
                filepath = os.path.join(source_dir, os.path.basename(requested_filename)) # Use basename for security

                print(f"[{self.address}] Client requested to download '{requested_filename}' from '{source_dir}'.")

                if not os.path.exists(filepath) or not os.path.isfile(filepath):
                    print(f"[{self.address}] Requested '{requested_filename}' from '{source_dir}' but it was not found.")
                    response = f"{self.FILE_NOT_FOUND_RESPONSE}{self.separator}{requested_filename}".encode('utf-8')
                    self.client_socket.sendall(response)
                    return # Exit after sending error response

                filesize = os.path.getsize(filepath)
                encoded_filename = os.path.basename(requested_filename).encode('utf-8')
                response_metadata = f"{self.DOWNLOAD_START_RESPONSE}{self.separator}{encoded_filename.decode('utf-8')}{self.separator}{filesize}".encode('utf-8')
                self.client_socket.sendall(response_metadata)
                print(f"[{self.address}] Sent download metadata for '{requested_filename}'.")

                # --- Server waits for client's ACK before sending file data ---
                client_ready_ack = self.client_socket.recv(self.buffer_size).decode('utf-8')
                if client_ready_ack != "READY_TO_RECEIVE_FILE_DATA":
                    print(f"[{self.address}] Client not ready for file data. Response: {client_ready_ack}")
                    return # Abort if client doesn't send expected ACK
                print(f"[{self.address}] Received client's 'READY_TO_RECEIVE_FILE_DATA' ACK.")

                self._serve_file_to_client(self.client_socket, filepath, requested_filename, filesize)

                # --- Server waits for final client status after sending file ---
                final_client_status = self.client_socket.recv(self.buffer_size).decode('utf-8')
                print(f"[{self.address}] Client reported file reception status: {final_client_status}")
            else:
                print(f"[{self.address}] Unknown command received: {command}")
                self.client_socket.sendall("UNKNOWN_COMMAND".encode('utf-8'))

        except (ConnectionResetError, BrokenPipeError):
            print(f"[{self.address}] Connection lost unexpectedly.")
        except socket.timeout: # Added timeout handling for recv calls
            print(f"[{self.address}] Socket timeout during command reception.")
        except ValueError:
            print(f"[{self.address}] Error: Invalid data format received. Check client protocol or malformed message.")
        except Exception as e:
            print(f"[{self.address}] An unexpected error occurred in run method: {e}")
        finally:
            print(f"[{self.address}] Handler closing connection.")
            try:
                # Proper shutdown for SSL sockets
                self.client_socket.shutdown(socket.SHUT_RDWR)
                self.client_socket.close()
            except OSError as e:
                if e.errno != 107: # 107 is 'Transport endpoint is not connected'
                    print(f"[{self.address}] Warning: Error during SSL socket shutdown/close: {e}")
            except Exception as e:
                print(f"[{self.address}] Unexpected error during final socket close: {e}")


    def _receive_file_data(self, client_socket: socket.socket, filepath: str, filesize: int, display_filename: str) -> bool:
        # Helper method to receive file data into a specified path.
        try:
            # Use 'leave=False' to clear the tqdm bar after completion, or 'leave=True' to keep it.
            progress = tqdm.tqdm(range(filesize), f"Receiving {os.path.basename(display_filename)}", unit="B", unit_scale=True, unit_divisor=1024, leave=False)
            with open(filepath, "wb") as f:
                bytes_received = 0
                while bytes_received < filesize:
                    # Make sure to request only the remaining bytes if the last chunk is smaller than buffer_size
                    bytes_to_read = min(filesize - bytes_received, self.buffer_size)
                    bytes_read = client_socket.recv(bytes_to_read)
                    if not bytes_read:
                        print(f"[{self.address}] Warning: Connection broken during file reception for {display_filename} (received {bytes_received}/{filesize} bytes).")
                        break # Client disconnected prematurely
                    f.write(bytes_read)
                    bytes_received += len(bytes_read)
                    progress.update(len(bytes_read))
            progress.close()

            if bytes_received == filesize:
                print(f"[{self.address}] Successfully received '{display_filename}' and saved to '{filepath}'.")
                return True
            else:
                print(f"[{self.address}] Warning: Received {bytes_received} bytes, expected {filesize} bytes for '{display_filename}'. File might be incomplete.")
                return False

        except FileNotFoundError:
            print(f"[Client {self.address}] Error: Could not open file for writing at '{filepath}'. Check permissions.")
            return False
        except OSError as e:
            print(f"[Client {self.address}] An OS error occurred while writing file to '{filepath}': {e}")
            return False
        except Exception as e:
            print(f"[Client {self.address}] An error occurred during file data reception in _receive_file_data: {e}")
            return False


    def _serve_file_to_client(self, client_socket: socket.socket, filepath: str, requested_filename: str, filesize: int):
        # Helper method to send a file to the client.

        try:
            print(f"[{self.address}] Serving '{requested_filename}' ({filesize} bytes) from '{filepath}'...")

            progress = tqdm.tqdm(range(filesize), f"Serving {os.path.basename(requested_filename)}", unit="B", unit_scale=True, unit_divisor=1024, leave=False)
            with open(filepath, "rb") as f:
                while True:
                    bytes_read = f.read(self.buffer_size)
                    if not bytes_read:
                        break
                    client_socket.sendall(bytes_read)
                    progress.update(len(bytes_read))
            progress.close()
            print(f"[{self.address}] Successfully served '{requested_filename}'.")

        except FileNotFoundError:
            print(f"[{self.address}] Error: File '{requested_filename}' disappeared during serving.")
        except OSError as e:
            print(f"[{self.address}] An OS error occurred while serving file from '{filepath}': {e}")
        except Exception as e:
            print(f"[{self.address}] An unexpected error occurred during file serving in _serve_file_to_client: {e}")


    def _handle_list_shared_files(self, client_socket: socket.socket):
        # Helper method to list files in the shared_uploads directory.
        try:
            shared_files = [f for f in os.listdir(self.shared_uploads_dir) if os.path.isfile(os.path.join(self.shared_uploads_dir, f))]

            if not shared_files:
                response = self.NO_FILES_SHARED_RESPONSE.encode('utf-8')
                client_socket.sendall(response)
                print(f"[{self.address}] No shared files to list.")
                return

            files_list_str = "|||".join(shared_files)

            response = f"{self.SHARED_LIST_RESPONSE}{self.separator}{files_list_str}".encode('utf-8')
            client_socket.sendall(response)
            print(f"[{self.address}] Sent list of shared files.")

        except Exception as e:
            print(f"[{self.address}] Error listing shared files: {e}")
            client_socket.sendall("SERVER_ERROR".encode('utf-8')) # Generic error response