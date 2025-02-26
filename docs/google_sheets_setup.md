# Google Sheets Export Setup Guide

This guide explains how to set up Google Sheets integration for exporting registered users from the bot.

## 1. Create a Google Cloud Project

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Click on "Create Project" or select an existing project
3. Give your project a name (e.g., "146-Meetup-Bot") and click "Create"

## 2. Enable Required APIs

1. In your project, go to "APIs & Services" > "Library"
2. Search for and enable the following APIs:
   - Google Sheets API
   - Google Drive API

## 3. Create a Service Account

1. Go to "APIs & Services" > "Credentials"
2. Click "Create Credentials" > "Service Account"
3. Enter a name for your service account (e.g., "bot-sheets-access")
4. Optionally add a description
5. Click "Create and Continue"
6. For role, select "Basic" > "Editor" (or a more restrictive role if preferred)
7. Click "Continue" and then "Done"

## 4. Create Service Account Key

1. In the Service Accounts list, find the account you just created
2. Click the three dots menu (⋮) > "Manage keys"
3. Click "Add Key" > "Create new key"
4. Select "JSON" format and click "Create"
5. The key file will be downloaded to your computer - keep this secure!

## 5. Prepare the Credentials for the Bot

You have three options for providing the service account credentials:

### Option 1: Base64 Encoded (Recommended for containers)

1. Use the following Python script to encode your credentials file:

```python
import base64
import sys
from pathlib import Path

def encode_json_file(file_path):
    path = Path(file_path)
    if not path.exists():
        print(f"Error: File {file_path} not found")
        return
    
    try:
        with open(path, 'r') as file:
            content = file.read()
        
        encoded_bytes = base64.b64encode(content.encode('utf-8'))
        encoded_string = encoded_bytes.decode('utf-8')
        
        print(f"GOOGLE_CREDENTIALS_BASE64={encoded_string}")
        
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python encode_json.py path/to/credentials.json")
    else:
        encode_json_file(sys.argv[1])
```

2. Run the script with your credentials file:
   ```
   python encode_json.py path/to/your/credentials.json
   ```

3. Copy the output to your `.env` file

### Option 2: JSON String (Original method)

1. Open the downloaded JSON file in a text editor
2. Copy the entire contents
3. In your `.env` file, add the following line:
   ```
   GOOGLE_CREDENTIALS_JSON=paste_the_entire_json_content_here
   ```
   Make sure the entire JSON is on a single line and properly escaped if necessary

### Option 3: Credentials File

1. Place your credentials file in a secure location
2. In your `.env` file, specify the path:
   ```
   GOOGLE_CREDENTIALS_FILE=path/to/your/credentials.json
   ```
   For the default location, name the file `google-service-user-credentials.json` in the project root

## 6. Create a Google Sheet

1. Go to [Google Sheets](https://sheets.google.com/) and create a new spreadsheet
2. Rename it to something meaningful (e.g., "146 Meetup Registrations")
3. Copy the spreadsheet ID from the URL:
   - The URL looks like: `https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit`
   - Copy the `SPREADSHEET_ID` part
4. Add this ID to your `.env` file:
   ```
   SPREADSHEET_ID=your_spreadsheet_id_here
   ```

## 7. Share the Spreadsheet with the Service Account

1. In your Google Sheet, click the "Share" button
2. In the service account JSON, find the `client_email` field (it looks like `something@project-id.iam.gserviceaccount.com`)
3. Enter this email address in the sharing dialog
4. Make sure to give "Editor" access
5. Uncheck "Notify people" and click "Share"

## 8. Test the Export

1. Make sure you've added your Telegram user ID to the `BOTSPOT_ADMINS` list in your `.env` file
2. Start the bot and use the `/export` command
3. The bot should export all registered users to your Google Sheet

## Troubleshooting

- **Permission denied errors**: Make sure you've shared the spreadsheet with the service account email
- **API not enabled errors**: Verify that both Google Sheets API and Google Drive API are enabled
- **Invalid credentials**: Check that the JSON in your `.env` file is properly formatted and complete
- **Admin access issues**: Ensure your Telegram user ID is correctly added to `BOTSPOT_ADMINS`

## Security Notes

- Keep your service account credentials secure - they grant access to your Google resources
- Consider using a more restrictive IAM role for the service account if possible
- For production use, consider storing credentials in a secure vault rather than directly in environment variables 