"""YouTube OAuth2 authentication module."""

import os
import pickle
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


# YouTube API scopes - we need force-ssl to update video metadata
SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl']

# Token storage path
TOKEN_FILE = Path('config/token.pickle')


class YouTubeAuthenticator:
    """Handles YouTube OAuth2 authentication and credential management."""

    def __init__(self, client_secrets_file: str = 'config/client_secrets.json'):
        """
        Initialize the authenticator.

        Args:
            client_secrets_file: Path to the OAuth2 client secrets JSON file
        """
        self.client_secrets_file = client_secrets_file
        self.credentials: Optional[Credentials] = None

    def authenticate(self) -> Credentials:
        """
        Authenticate with YouTube and return valid credentials.

        This method will:
        1. Try to load existing credentials from token file
        2. Refresh credentials if expired (and refresh token exists)
        3. Prompt user for authentication if no valid credentials exist

        Returns:
            Valid OAuth2 credentials

        Raises:
            FileNotFoundError: If client_secrets_file doesn't exist
        """
        if not os.path.exists(self.client_secrets_file):
            raise FileNotFoundError(
                f"Client secrets file not found: {self.client_secrets_file}\n"
                f"Please download it from Google Cloud Console and place it in the config/ directory."
            )

        # Try to load existing credentials
        if TOKEN_FILE.exists():
            with open(TOKEN_FILE, 'rb') as token:
                self.credentials = pickle.load(token)

        # If credentials don't exist or are invalid, authenticate
        if not self.credentials or not self.credentials.valid:
            if self.credentials and self.credentials.expired and self.credentials.refresh_token:
                # Refresh expired credentials
                print("Refreshing expired credentials...")
                self.credentials.refresh(Request())
            else:
                # Perform OAuth2 flow
                print("No valid credentials found. Starting authentication flow...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.client_secrets_file, SCOPES
                )
                self.credentials = flow.run_local_server(
                    port=8080,
                    prompt='consent',
                    authorization_prompt_message='Please visit this URL to authorize the application: {url}'
                )

            # Save credentials for future use
            TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(TOKEN_FILE, 'wb') as token:
                pickle.dump(self.credentials, token)
            print("Credentials saved successfully.")

        return self.credentials

    def get_youtube_service(self):
        """
        Get an authenticated YouTube API service.

        Returns:
            googleapiclient.discovery.Resource: YouTube API service object
        """
        if not self.credentials:
            self.authenticate()

        return build('youtube', 'v3', credentials=self.credentials)

    def revoke_credentials(self):
        """Revoke credentials and delete the token file."""
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
            print("Credentials revoked and token file deleted.")
        self.credentials = None
