# Vertec timesheets

A simple python scripts which logs into Vertec (<https://www.vertec.com>) and retrieves timesheets as JSON for the logged-in user.

In order to work, the script needs these three configurations, either provided as environment variables or interactively in case they are missing or empty.

- `VERTEC_URL`
- `VERTEC_USERNAME`
- `VERTEC_PASSWORD`

## Usage

```bash
    python3 -m virtualenv venv
    source venv/bin/activate
    pip3 install --upgrade pip
    pip3 install -r REQUIREMENTS.txt

    export VERTEC_URL=https://your-vertec.your-company.com
    export VERTEC_USERNAME=yourusername 

    python3 vertec-timesheets.py
```