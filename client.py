import socket
import tqdm
import os
import sys

class FileTransferClient:
    # Class initialization method
    def __init__(self, host: str, port: int, buffer_size: int = 4096, separator: str = "<SEPARATOR>", download_dir: str = "downloads"):
        self.host = host
        self.port = port
        self.buffer_size = buffer_size
        self.separator = separator
        self.s = None
        self.download_dir = download_dir 
        
        self.UPLOAD_PRIVATE_COMMAND = "UPLOAD_PRIVATE"
        self.DOWNLOAD_SERVER_PUBLIC_COMMAND = "DOWNLOAD_SERVER_PUBLIC"
        self.UPLOAD_FOR_SHARING_COMMAND = "UPLOAD_FOR_SHARE"
        self.LIST_SHARED_COMMAND = "LIST_SHARED"
        self.DOWNLOAD_SHARED_COMMAND = "DOWNLOAD_SHARED"
        
        self.DOWNLOAD_START_RESPONSE = "DOWNLOAD_START"
        self.FILE_NOT_FOUND_RESPONSE = "FILE_NOT_FOUND"
        self.SHARED_LIST_RESPONSE = "SHARED_LIST"
        self.NO_FILES_SHARED_RESPONSE = "NO_FILES_SHARED"

        self._create_download_directory()

    def _create_download_directory(self):
        if not os.path.exists(self.download_dir):
            try:
                os.makedirs(self.download_dir)
                print(f"Created download directory: '{self.download_dir}'")
            except OSError as e:
                print(f"Error creating download directory '{self.download_dir}': {e}")
                sys.exit(1)

    def connect(self) -> bool:
        if self.s:
            self.close_connection()
            
        print(f"Attempting to connect to {self.host}:{self.port}...")
        try:
            self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.s.connect((self.host, self.port))
            print("Successfully connected to the server.")
            return True
        except ConnectionRefusedError:
            print(f"Error: Connection refused. Is the server running on {self.host}:{self.port}?")
            return False
        except socket.gaierror:
            print(f"Error: Host '{self.host}' could not be resolved. Check the IP address or hostname.")
            return False
        except Exception as e:
            print(f"An unexpected error occurred during connection: {e}")
            return False

    def close_connection(self):
        if self.s:
            print("Closing connection...")
            self.s.close()
            self.s = None
            print("Connection closed.")

    def get_local_filename_from_user(self, prompt: str) -> tuple[str, int] | None:
        while True:
            user_input = input(f"{prompt} (or 'q' to quit): ")
            if user_input.lower() == 'q':
                print("Exiting file selection.")
                return None

            try:
                if not os.path.exists(user_input):
                    print(f"Error: File '{user_input}' not found. Please try again.\r\n")
                    continue
                if not os.path.isfile(user_input):
                    print(f"Error: '{user_input}' is a directory, not a file. Please enter a file path.\r\n")
                    continue
                filesize = os.path.getsize(user_input)
                print(f"Selected file: '{user_input}' (Size: {filesize} bytes.)")
                return user_input, filesize
            except OSError as e:
                print(f"An OS error occurred with '{user_input}': {e}. Please try again.\r\n")
            except Exception as e:
                print(f"An unexpected error occurred during file validation: {e}. Please try again.\r\n")

    def _send_file_to_server(self, command: str, filename: str, filesize: int):
        # Helper to send file metadata and then file data to the server.
        if not self.connect():
            return False

        try:
            encoded_filename = os.path.basename(filename).encode('utf-8')
            command_and_data = f"{command}{self.separator}{encoded_filename.decode('utf-8')}{self.separator}{filesize}".encode('utf-8')
            self.s.sendall(command_and_data)  # Send command and metadata only once

            progress = tqdm.tqdm(range(filesize), f"Sending {os.path.basename(filename)}", unit="B", unit_scale=True, unit_divisor=1024)
            with open(filename, "rb") as f:
                while True:
                    bytes_read = f.read(self.buffer_size)
                    if not bytes_read:
                        break
                    self.s.sendall(bytes_read)
                    progress.update(len(bytes_read))
            progress.close()
            print(f"File '{filename}' sent successfully.")
            return True
        except BrokenPipeError:
            print("Error: Connection lost to the server (Broken pipe).")
        except ConnectionResetError:
            print("Error: Connection reset by peer. Server might have closed the connection unexpectedly.")
        except Exception as e:
            print(f"An unexpected error occurred during file transfer: {e}")
        finally:
            self.close_connection()
        return False

    def _receive_file_from_server(self, remote_filename: str, command: str):
        # Helper to receive file data from the server after sending the download command once.
        if not self.connect():
            return False

        try:
            # Send the download command and filename once
            command_and_data = f"{command}{self.separator}{remote_filename}".encode('utf-8')
            print(f"Sending download command: {command_and_data.decode('utf-8')}")
            self.s.sendall(command_and_data)   

            response = self.s.recv(self.buffer_size).decode('utf-8')
            parts = response.split(self.separator)
            command_response = parts[0]
            
            if command_response == self.DOWNLOAD_START_RESPONSE:
                filename_encoded = parts[1]
                filesize_str = parts[2]
                
                actual_filename = filename_encoded.encode('utf-8').decode('utf-8')
                filesize = int(filesize_str)

                local_save_path = os.path.join(self.download_dir, os.path.basename(actual_filename)) 

                print(f"Receiving '{actual_filename}' ({filesize} bytes) from server...")

                progress = tqdm.tqdm(range(filesize), f"Downloading {actual_filename}", unit="B", unit_scale=True, unit_divisor=1024)
                with open(local_save_path, "wb") as f:
                    bytes_received = 0
                    while bytes_received < filesize:
                        bytes_read = self.s.recv(self.buffer_size)
                        if not bytes_read:
                            break
                        f.write(bytes_read)
                        bytes_received += len(bytes_read)
                        progress.update(len(bytes_read))
                progress.close()

                if bytes_received == filesize:
                    print(f"Successfully downloaded '{actual_filename}' to '{local_save_path}'.")
                else:
                    print(f"Warning: Download of '{actual_filename}' incomplete. Expected {filesize} bytes, got {bytes_received}.")
                return True
            
            elif command_response == self.FILE_NOT_FOUND_RESPONSE:
                print(f"Error: File '{parts[1]}' not found on the server.")
                return False
            else:
                print(f"Server responded with an unknown command: {command_response}")
                return False

        except BrokenPipeError:
            print("Error: Connection lost to the server (Broken pipe).")
        except ConnectionResetError:
            print("Error: Connection reset by peer. Server might have closed the connection unexpectedly.")
        except ValueError:
            print("Error: Invalid response received from server. Check server logs.")
        except Exception as e:
            print(f"An unexpected error occurred during file download: {e}")
        finally:
            self.close_connection()
        return False

    def upload_private_file(self):
        file_info = self.get_local_filename_from_user("Enter the filename to upload privately")
        if file_info is None:
            return
        filename, filesize = file_info
        self._send_file_to_server(self.UPLOAD_PRIVATE_COMMAND, filename, filesize)

    def download_server_public_file(self):
        remote_filename = input("Enter the filename to download from server's public folder (or 'q' to quit): ")
        if remote_filename.lower() == 'q':
            print("Exiting download selection.")
            return
        
        self._receive_file_from_server(remote_filename, self.DOWNLOAD_SERVER_PUBLIC_COMMAND)

    def upload_file_for_sharing(self):
        file_info = self.get_local_filename_from_user("Enter the filename to upload for sharing")
        if file_info is None:
            return
        filename, filesize = file_info
        self._send_file_to_server(self.UPLOAD_FOR_SHARING_COMMAND, filename, filesize)

    def list_and_download_shared_files(self):
        if not self.connect():
            return
        
        try:
            self.s.sendall(self.LIST_SHARED_COMMAND.encode('utf-8'))
            
            response = self.s.recv(self.buffer_size).decode('utf-8')
            parts = response.split(self.separator, 1)

            command = parts[0]

            if command == self.SHARED_LIST_RESPONSE:
                if len(parts) > 1:
                    shared_files = parts[1].split("|||")
                    print("\n--- Available Shared Files ---")
                    for i, fname in enumerate(shared_files):
                        print(f"{i+1}. {fname}")
                    print("------------------------------")

                    while True:
                        choice_str = input("Enter number to download, 'l' to list again, or 'q' to quit: ").strip().lower()
                        if choice_str == 'q':
                            print("Exiting shared file download.")
                            break
                        if choice_str == 'l':
                            self.close_connection()
                            self.list_and_download_shared_files()
                            return
                        try:
                            choice_idx = int(choice_str) - 1
                            if 0 <= choice_idx < len(shared_files):
                                file_to_download = shared_files[choice_idx]
                                print(f"Attempting to download '{file_to_download}'...")
                                self.close_connection()
                                if self.connect():
                                    self._receive_file_from_server(file_to_download, self.DOWNLOAD_SHARED_COMMAND)
                                break
                            else:
                                print("Invalid number. Please try again.")
                        except ValueError:
                            print("Invalid input. Please enter a number, 'l', or 'q'.")
                else:
                    print("Server responded with SHARED_LIST but no files. (Possible protocol error)")

            elif command == self.NO_FILES_SHARED_RESPONSE:
                print("No files currently available for sharing on the server.")
            elif command == "SERVER_ERROR":
                print("Server encountered an error while listing shared files.")
            else:
                print(f"Server responded with an unknown command: {command}")

        except BrokenPipeError:
            print("Error: Connection lost to the server (Broken pipe).")
        except ConnectionResetError:
            print("Error: Connection reset by peer. Server might have closed the connection unexpectedly.")
        except ValueError:
            print("Error: Invalid response received from server for shared list. Check server logs.")
        except Exception as e:
            print(f"An unexpected error occurred during shared file listing: {e}")
        finally:
            self.close_connection()

    def start_interactive_session(self):
        while True:
            print("\n--- File Transfer Client ---")
            print("1. Upload a file (Private to Server)")
            print("2. Download a file (From Server's Public Folder)")
            print("3. Upload a file (For Sharing with Other Clients)")
            print("4. List & Download Shared Files")
            print("q. Quit")
            choice = input("Enter your choice: ").strip().lower()

            if choice == '1':
                self.upload_private_file()
            elif choice == '2':
                self.download_server_public_file()
            elif choice == '3':
                self.upload_file_for_sharing()
            elif choice == '4':
                self.list_and_download_shared_files()
            elif choice == 'q':
                print("Exiting client.")
                break
            else:
                print("Invalid choice. Please try again.")

if __name__ == "__main__":
    SERVER_HOST = "192.168.0.2"
    SERVER_PORT = 5000

    client = FileTransferClient(SERVER_HOST, SERVER_PORT)
    client.start_interactive_session()

