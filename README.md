# **Simple Python File Transfer System**

A basic client-server application for transferring files over a local network. It supports private uploads, downloads from a server's public folder, and client-to-client file exchange mediated by the server.

**Developer:** Israel Mawuenyega Akpadja

## **Table of Contents**

1. [Features](#bookmark=id.fu04efba53rf)  
2. [Prerequisites](#bookmark=id.itplqq5f1psw)  
3. [Installation](#bookmark=id.ec9cjh6ragp0)  
4. [Project Structure](#bookmark=id.p26kws684u4)  
5. [Usage](#bookmark=id.2uf3iu9g1ypg)  
   * [Starting the Server](#bookmark=id.wypctahdbkch)  
   * [Starting and Using the Client](#bookmark=id.jru9penb6xd9)  
   * [Performing a Client-to-Client File Transfer](#bookmark=id.ud04o3xbxcnz)  
6. [Directory Explanations](#bookmark=id.xcy6x3v1mnxe)  
7. [Troubleshooting](#bookmark=id.gdfjguhzli2a)

## **Features**

* **Multi-threaded Server:** The server can handle multiple client connections concurrently, allowing simultaneous uploads and downloads.  
* **File Upload (Private):** Clients can upload files to a private folder on the server (uploads/).  
* **File Download (Server Public):** Clients can download files from a designated public folder on the server (shared\_files/).  
* **Server-Mediated Client-to-Client Transfer:**  
  * Clients can upload files to a shared staging area on the server (shared\_uploads/).  
  * Other clients can then list and download these shared files from the server.  
* **Progress Bars:** Uses tqdm to show transfer progress for both uploads and downloads, providing real-time feedback.  
* **Robust Error Handling:** Includes basic error handling for network issues, file operations, and unexpected disconnections.  
* **Dedicated Directories:** Automatically organizes uploaded, shared, and downloaded files into specific, clearly named folders.

## **Prerequisites**

Before running the application, ensure you have:

* **Python 3.x** installed on your system.  
* The tqdm Python library installed. You can install it via pip:  
  pip install tqdm

## **Installation**

1. **Download/Copy the files:** Save server.py, client.py, and thread\_functions.py into the same directory on your computer (e.g., a new folder named FileTransferApp).

## **Project Structure**

After running the server for the first time, your project directory will look similar to this:

FileTransferApp/  
├── client.py  
├── server.py  
├── thread\_functions.py  
├── uploads/             \# Server: Stores files uploaded privately by clients  
├── shared\_files/        \# Server: Stores files prepared by the server for public download  
├── shared\_uploads/      \# Server: Stores files uploaded by clients \*for sharing\* with other clients  
└── downloads/           \# Client: Stores files downloaded by the client

## **Usage**

You will typically need two or more separate terminal windows (or command prompts) to run the server and multiple clients concurrently.

### **Starting the Server**

1. **Open your first terminal/command prompt.**  
2. **Navigate to the directory** where you saved server.py:  
   cd /path/to/FileTransferApp

3. **Run the server script:**  
   python server.py

   You should see output indicating directory creation and that the server is listening:  
   Created directory: 'uploads'  
   Created directory: 'shared\_files'  
   Created directory: 'shared\_uploads'  
   \[\*\] Listening as 127.0.0.1:5000  
   Private uploads to: uploads  
   Public files for download from server: shared\_files  
   Files uploaded for sharing: shared\_uploads

   Waiting for a client connection...

   **Keep this terminal open and running.**

### **Starting and Using the Client**

1. **Open your second terminal/command prompt (and third, fourth, etc., for multiple clients).**  
2. **Navigate to the same directory** where you saved client.py:  
   cd /path/to/FileTransferApp

3. **Run the client script:**  
   python client.py

   The client will display an interactive menu:  
   \--- File Transfer Client \---  
   1\. Upload a file (Private to Server)  
   2\. Download a file (From Server's Public Folder)  
   3\. Upload a file (For Sharing with Other Clients)  
   4\. List & Download Shared Files  
   q. Quit  
   Enter your choice:

#### **Client Menu Options:**

* **1 (Upload a file \- Private to Server):**  
  * Uploads a file from your local machine to the server's uploads/ directory.  
  * **Usage:** Place the file (e.g., my\_private\_doc.txt) in the *same directory* as client.py, then choose option 1 and enter its name.  
* **2 (Download a file \- From Server's Public Folder):**  
  * Downloads a file from the server's shared\_files/ directory.  
  * **Preparation:** Place the file you want to download (e.g., public\_report.pdf) directly into the shared\_files/ directory on the server machine.  
  * **Usage:** Choose option 2 and enter the exact filename.  
* **3 (Upload a file \- For Sharing with Other Clients):**  
  * Uploads a file from your local machine to the server's shared\_uploads/ directory, making it available for other clients to download.  
  * **Usage:** Place the file (e.g., photo.jpg) in the *same directory* as client.py, then choose option 3 and enter its name.  
* **4 (List & Download Shared Files):**  
  * Connects to the server, retrieves a list of all files currently in the shared\_uploads/ directory (uploaded by any client), and allows you to select one to download.  
  * **Usage:** Choose option 4\. The client will display a numbered list. Enter the number of the file you wish to download.  
* **q (Quit):**  
  * Exits the client application gracefully.

### **Performing a Client-to-Client File Transfer**

This process involves **Client A uploading a file for sharing**, and then **Client B downloading that shared file**.

**Example Scenario:** Client A wants to send my\_great\_idea.txt to Client B.

1. **Prepare the File:**  
   * Make sure my\_great\_idea.txt exists in the same directory as your client.py script.  
2. **Start the Server (if not already running):**  
   * In **Terminal 1**, run python server.py.  
3. **Client A Uploads for Sharing:**  
   * In **Terminal 2**, run python client.py.  
   * From the menu, choose option **3** (Upload a file \- For Sharing with Other Clients).  
   * When prompted, enter: my\_great\_idea.txt  
   * The file will be uploaded to the server's shared\_uploads/ directory. You'll see confirmation in both Client A's and the Server's terminals.  
4. **Client B Downloads the Shared File:**  
   * In **Terminal 3** (or you can restart Client A's terminal and run client.py again, acting as Client B), run python client.py.  
   * From the menu, choose option **4** (List & Download Shared Files).  
   * The client will display a list of all files available in the shared\_uploads/ folder. You should see my\_great\_idea.txt in this list.  
   * Enter the **number** corresponding to my\_great\_idea.txt (e.g., 1 if it's the first in the list).  
   * The file will be downloaded and saved into Client B's local downloads/ folder. You'll see confirmation in Client B's and the Server's terminals.

## **Directory Explanations**

* **uploads/ (Server-side):**  
  * Automatically created by the server.  
  * Stores files uploaded using the "Upload a file (Private to Server)" option. These are generally intended for the server's use or private storage.  
* **shared\_files/ (Server-side):**  
  * Automatically created by the server.  
  * **Important:** Only files manually placed *inside this directory* on the server machine will be available for clients to download using the "Download a file (From Server's Public Folder)" option.  
* **shared\_uploads/ (Server-side):**  
  * Automatically created by the server.  
  * This is the staging area for client-to-client transfers. Files uploaded here using the "Upload a file (For Sharing with Other Clients)" option become visible to all clients using the "List & Download Shared Files" option.  
* **downloads/ (Client-side):**  
  * Automatically created by the client.  
  * All files downloaded *from* the server (whether from shared\_files/ or shared\_uploads/) will be saved here.

## **Troubleshooting**

* **"Error: File 'filename.txt' not found." (Client Upload):**  
  * Ensure filename.txt is in the *same directory* as your client.py script.  
  * Check for typos in the filename.  
* **"Error: File 'filename.txt' not found on the server." (Client Download):**  
  * **For option 2 (Download from Server's Public Folder):** Ensure filename.txt is located in the **shared\_files/ directory** on the server's machine.  
  * **For option 4 (List & Download Shared Files):** Ensure filename.txt was successfully uploaded into the **shared\_uploads/ directory** on the server.  
  * Check for typos in the filename.  
* **"Error: Connection refused." (Client):**  
  * The server is likely not running, or it's running on a different IP address/port.  
  * Make sure you started server.py in its own terminal window *before* running any client.py instances.  
  * Verify that SERVER\_HOST and SERVER\_PORT in both client.py and server.py match (default 127.0.0.1 and 5000).  
* **"Address already in use" (Server):**  
  * This means the server was not shut down cleanly, and the port is still occupied.  
  * Wait a minute or two and try restarting the server. The SO\_REUSEADDR option should help mitigate this, but it can still occur sometimes.  
  * Ensure no other application is using port 5000\.  
* **Progress bar seems stuck or transfer fails mid-way:**  
  * Could indicate a network issue or the other side of the connection closed unexpectedly. Check the console output for specific error messages in both client and server terminals.