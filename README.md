# **Simple Python File Transfer System**

A secure, client-server application for transferring files. It supports private uploads, public downloads, and client-to-client file exchange. The system uses authentication and roles to manage access to files.

**Developer:** Israel Mawuenyega Akpadja

## **Table of Contents**

1.  [Features](https://www.google.com/search?q=%23bookmark%3Did.fu04efba53rf)
2.  [Prerequisites](https://www.google.com/search?q=%23bookmark%3Did.itplqq5f1psw)
3.  [Installation](https://www.google.com/search?q=%23bookmark%3Did.ec9cjh6ragp0)
4.  [Project Structure](https://www.google.com/search?q=%23bookmark%3Did.p26kws684u4)
5.  [Usage](https://www.google.com/search?q=%23bookmark%3Did.2uf3iu9g1ypg)
      * [Starting the Server](https://www.google.com/search?q=%23bookmark%3Did.wypctahdbkch)
      * [Starting and Using the Client](https://www.google.com/search?q=%23bookmark%3Did.jru9penb6xd9)
6.  [Directory Explanations](https://www.google.com/search?q=%23bookmark%3Did.xcy6x3v1mnxe)
7.  [Troubleshooting](https://www.google.com/search?q=%23bookmark%3Did.gdfjguhzli2a)

-----

## **Features**

  * **Secure Authentication:** Users must register and log in to access most features, ensuring a secure environment.
  * **Role-Based Access Control:** Differentiates between `user` and `admin` roles, granting administrators additional file management privileges.
  * **SSL/TLS Encryption:** All client-server communication is encrypted using SSL/TLS for enhanced security.
  * **Multi-threaded Server:** The server can handle multiple client connections concurrently.
  * **File Upload (Private):** Clients can upload files to their personal private folder on the server.
  * **File Sharing:**
      * **Public Files:** Users can make their private files available for public download by all clients.
      * **Shared Files:** Users can make their private files available for download by other logged-in users.
  * **Administrator Capabilities:** Admins can manage files in other users' private or shared directories, including making a user's file public.
  * **Progress Bars:** Uses `tqdm` to show transfer progress for both uploads and downloads.
  * **Robust Error Handling:** Includes error handling for network issues, file operations, and unexpected disconnections.
  * **Dedicated Directories:** Automatically organizes uploaded, public, and shared files into specific, clearly named folders.

## **Prerequisites**

Before running the application, ensure you have:

  * **Python 3.x** installed.
  * The required Python libraries. You can install them via pip:
    ```
    pip install tqdm bcrypt pymysql pymysql-pool dotenv requests 
    ```

## **Installation**

1.  **Download/Copy the files:** Save all Python files (`server.py`, `client.py`, etc.) and your `config.ini`into the same directory.
2.  **Generate SSL certificate and key:** Ensure you have a valid `server.crt` and `server.key` file in the project directory for secure communication. You can generate them using OpenSSL.
3.  **Configure Database:** Set up your MySQL database and update the database configuration in `config.ini`. In addition, configure your database password in `.env.example` and then rename it to `.env`.

## **Project Structure**

After running the server for the first time, your project directory will look similar to this:

```
FileTransferApp/
├── client.py
├── server.py
├── server_auth.py
├── thread_functions.py
├── config.ini
├── server.crt
├── server.key
├── uploads/              # Server: Stores private files uploaded by each client (e.g., uploads/username/)
├── public_files/         # Server: Stores files made public by any user or admin
├── shared_uploads/       # Server: Stores files made shared by clients for other users to download
└── downloads/            # Client: Stores files downloaded by the client
```

## **Usage**

You will typically need two or more separate terminal windows to run the server and multiple clients concurrently.

### **Starting the Server**

1.  **Open your first terminal.**
2.  **Navigate to the project directory:** `cd /path/to/FileTransferApp`
3.  **Run the server script:** `python server.py`
    You should see output indicating directory creation, database connection, and that the server is listening. **Keep this terminal open and running.**

### **Starting and Using the Client**

1.  **Open a new terminal for each client.**
2.  **Navigate to the project directory:** `cd /path/to/FileTransferApp`
3.  **Run the client script:** `python client.py`
    The client will display an interactive menu, starting with login and registration.

#### **Client Usage:**
   Refer to the commands in `config.ini` to sue it, since this is planned to be used as an API for a web client, so extensive console-based interactive capabilities have not been implemented. Type the exact values of the command constants as declared in the configuration file. Any errors will be reported for your understanding. 

-----

## **Directory Explanations**

  * **uploads/ (Server-side):** Stores private uploads. Each user gets their own subdirectory (e.g., `uploads/israel/`). Only that user and an admin can access these files.
  * **public\_files/ (Server-side):** Contains files that have been made public. Any client, logged in or not, can download files from this directory.
  * **shared\_uploads/ (Server-side):** This is the staging area for user-to-user transfers. Files uploaded here using the "Make a private file shared" option are stored in a user-specific folder (e.g., `shared_uploads/israel/`) and are visible to all other logged-in clients.
  * **downloads/ (Client-side):** All files downloaded from the server will be saved here.

## **Troubleshooting**

  * **"Error: File 'filename.txt' not found." (Client Upload):**
      * Ensure the file is in the same directory as your client script or provide the full path.
  * **"Error: File 'filename.txt' not found on the server." (Client Download):**
      * Verify the file exists in the correct server-side directory (`public_files/`, `shared_uploads/username/`, or the specified admin path).
  * **"Error: Connection refused." (Client):**
      * Ensure the server is running on the correct host and port (`config.ini`).
  * **`TypeError: string indices must be integers, not 'str'` (Server):**
      * This is a common bug indicating a mismatch in how session data is stored. Ensure your `server_auth.py` file is correctly storing a dictionary for each session, not just a string, as per the latest fixes.
  * **Progress bar stuck or transfer fails:**
      * Check for network issues or unexpected disconnections. Examine both client and server logs for specific error messages.