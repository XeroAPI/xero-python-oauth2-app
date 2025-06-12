# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Flask web application that demonstrates OAuth 2.0 authentication with the Xero API. It serves as a companion app showing how to connect to Xero organizations and make real API calls to various Xero endpoints.

## Development Environment Setup

### Prerequisites
- Python 3.5+
- Git
- SSH keys configured for GitHub access (required for Flask-Session dependency)

### Local Development Commands
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the main application
python3 app.py

# Application will be available at http://localhost:5000/login
```

## Configuration

The application requires a `config.py` file in the root directory with Xero API credentials:
```python
CLIENT_ID = "...client id string..."
CLIENT_SECRET = "...client secret string..."
STATE = "...my super secure state..."
```

Use `example_config.py` as a template. The STATE field cannot be empty.

## Architecture

### Core Files
- `app.py`: Main Flask application with OAuth2 flow and API demonstrations
- `app2.py`: Additional utility functions for bank transaction matching
- `utils.py`: JSON serialization utilities and custom encoders for Xero Python SDK models
- `default_settings.py`: Flask configuration for development environment
- `logging_settings.py`: Logging configuration for debugging API calls

### Key Components
- **OAuth2 Flow**: Implemented using flask-oauthlib with token persistence via flask-session
- **Token Management**: Automatic refresh of expired access tokens
- **API Client**: Xero Python SDK v6.1.0 with comprehensive API coverage
- **Session Storage**: File-based session storage in `cache/` directory

### Xero API Integration
The app demonstrates integration with multiple Xero APIs:
- Accounting API (invoices, contacts, organizations)
- Assets API
- Project API  
- Payroll APIs (AU, UK, NZ)
- Files API
- Finance API

Token exchange between flask-oauthlib and xero-python SDK is handled by decorator functions that persist tokens in Flask sessions.

## Testing with Demo Company
Always use Xero's Demo Company for testing to avoid affecting real data. The application includes functionality to connect to organizations and perform various API operations safely in the demo environment.