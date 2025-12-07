# Comic Library Archive Standardizer v1.0

A powerful tool to standardize comic book archives by converting all files to CBZ format with consistent naming and organization.

## Features

- **Convert RAR to ZIP**: All `.cbr` (RAR) files are converted to `.cbz` (ZIP) format
- **Fix Misnamed Files**: Corrects files with wrong extensions (e.g., ZIP files named `.cbr`)
- **Intelligent Duplicate Handling**: When renaming creates conflicts, keeps the best version
- **Configurable Organization**: Files organized by publisher/series based on `config.ini`
- **Safety First**: Creates backups before any modifications
- **Dry Run Mode**: Preview changes without modifying files
- **Parallel Processing**: Uses multiple CPU cores for faster processing
- **Comprehensive Reporting**: Generates detailed JSON/CSV reports of all changes

## Installation

1. Ensure you have Python 3.8 or higher installed
2. Install required dependencies:

```bash
pip install -r requirements.txt
