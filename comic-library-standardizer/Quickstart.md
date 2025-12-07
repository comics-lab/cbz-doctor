Comic Library Standardizer - QuickStart Guide

Quick Start

Follow these steps to get started quickly:

Step 1: Create a Configuration File

```bash
python comic_library.py --directory /path/to/your/comics --create-config
```

This creates a config.ini file in your comics directory with default settings.

Step 2: Edit the Configuration File

Open the generated config.ini and customize it for your needs:

· Set your actual comics directory path
· Adjust folder structure and file naming patterns
· Configure processing options

Step 3: Preview Changes (Dry Run)

```bash
python comic_library.py --config /path/to/your/comics/config.ini --dry-run
```

This simulates the process without making any changes. Review the output to ensure everything looks correct.

Step 4: Process Your Library

```bash
python comic_library.py --config /path/to/your/comics/config.ini
```

This will:

· Convert all RAR files to ZIP format
· Fix misnamed files
· Organize files into the specified folder structure
· Resolve duplicates intelligently
· Generate a detailed report

---

Configuration (config.ini)

Your configuration file controls everything. Here's what each section does:

General Section

```ini
[General]
destination_dir = /path/to/comic/library      # Your comics folder
folder_format = {publisher}/{series}           # How to organize folders
file_format = {series} v{volume:02d}          # How to name files
```

Processing Section

```ini
[Processing]
backup_files = yes    # Create backups before modifying files
dry_run = no          # Set to 'yes' for testing only
workers = 8           # Number of parallel processes (CPU cores)
```

Output Section

```ini
[Output]
log_level = INFO      # DEBUG, INFO, WARNING, ERROR
log_file = /path/to/logs/processing.log
report_file = /path/to/reports/library_report.json
```

---

Folder and File Format Variables

Folder Format Variables

Use these in folder_format:

· {publisher}: Publisher name (extracted from folder structure)
· {series}: Series name (extracted from folder structure)
· {PUBLISHER}: Publisher name in UPPERCASE
· {SERIES}: Series name in UPPERCASE

Examples:

· {publisher}/{series} → DC Comics/Batman/
· Comics/{publisher}/{SERIES} → Comics/DC Comics/BATMAN/

File Format Variables

Use these in file_format:

· {series}: Series name
· {volume}: Volume number (extracted from filename)
· {publisher}: Publisher name
· {SERIES}: Series name in UPPERCASE

Examples:

· {series} v{volume:02d} → Batman v01.cbz
· {publisher} - {series} #{volume} → DC Comics - Batman #1.cbz

---

Duplicate Resolution Rules

When two files would have the same name after processing, the script uses this priority:

1. File Count: Archive with more files wins
2. File Dates: Archive with newer files wins
3. File Size: Larger archive wins (tiebreaker)

Example:

· batman_01.cbr (50 files, last modified 2023) vs batman_01.cbz (45 files, last modified 2024)
· Winner: batman_01.cbr (more files, even though older)

---

Example Workflow

Before Processing:

```
Comics/
├── Batman/
│   ├── batman_01.cbr    (actually a ZIP file - misnamed!)
│   ├── batman_01.rar    (RAR format - needs conversion)
│   └── batman_02.cbr    (correct RAR format)
├── Spiderman/
│   └── spidey_v1.cbz    (correct ZIP format)
└── X-Men/
    ├── xmen_01.cbr
    └── xmen_01.zip      (duplicate with different format)
```

After Processing:

```
Comics/
├── DC Comics/
│   └── Batman/
│       ├── Batman v01.cbz  (converted from RAR + renamed)
│       └── Batman v02.cbz  (converted from RAR)
├── Marvel Comics/
│   ├── Spider-Man/
│   │   └── Spider-Man v01.cbz  (kept, already correct)
│   └── X-Men/
│       └── X-Men v01.cbz       (best duplicate kept)
└── processing_report.json      (detailed report of all changes)
```

---

Command Line Options

```
-c, --config CONFIG.INI   Configuration file (required unless using --create-config)
-d, --directory DIR       Library directory (use with --create-config)
--create-config           Create default config.ini and exit
--dry-run                 Simulate changes without modifying files
--no-backup               Disable backup creation (not recommended!)
-w, --workers N           Number of parallel workers (default: CPU cores)
-l, --log-level LEVEL     Logging level: DEBUG, INFO, WARNING, ERROR
--report FILE             Override report file location
```

Common Usage Examples:

Basic processing with defaults:

```bash
python comic_library.py --config /comics/config.ini
```

Test run first (highly recommended):

```bash
python comic_library.py --config /comics/config.ini --dry-run --log-level INFO
```

Parallel processing (faster for large libraries):

```bash
python comic_library.py --config /comics/config.ini --workers 12
```

Debug mode for troubleshooting:

```bash
python comic_library.py --config /comics/config.ini --log-level DEBUG
```

---

Safety Notes

⚠️ IMPORTANT SAFETY WARNINGS:

1. ALWAYS run --dry-run first to preview changes
2. Backups are created by default - don't disable unless you're sure
3. The script never deletes original files unless conversion is successful
4. Logs and reports provide a complete audit trail of all changes
5. Test on a small subset of your library first

Safety Features:

· Creates .bak backup files before any modification
· Can run in --dry-run mode to preview changes
· Comprehensive logging of every action
· Detailed JSON/CSV reports with full audit trail
· Graceful error handling continues processing other files

---

Troubleshooting

Common Issues and Solutions:

1. "RAR file format not supported"
   ```bash
   # Install additional RAR support
   pip install unrar
   # Or install system RAR tools
   # Ubuntu/Debian: sudo apt-get install unrar
   # macOS: brew install unrar
   # Windows: Install WinRAR or 7-Zip
   ```
2. "Permission denied" errors
   ```bash
   # Run with appropriate permissions
   sudo python comic_library.py --config /comics/config.ini
   # Or change directory permissions
   chmod -R 755 /path/to/comics
   ```
3. Slow processing
   · Reduce workers in config.ini (try 2-4 for CPU-intensive systems)
   · Ensure you're not running other heavy applications
   · Process smaller batches if memory is limited
4. Missing dependencies
   ```bash
   # Install all required packages
   pip install -r requirements.txt
   
   # If pip fails, try:
   python -m pip install --upgrade pip
   pip install rarfile
   ```
5. "No files found" error
   · Check destination_dir in config.ini points to correct location
   · Ensure files have valid extensions (.cbz, .cbr, .zip, .rar)
   · Check file permissions

---

Minimum Requirements

File Structure

You only need these two files:

```
comic-library-standardizer/
├── comic_library.py      # Main script
└── requirements.txt      # Python dependencies
```

Installation

```bash
# 1. Install Python 3.8 or higher (if not already installed)
#    Check: python3 --version

# 2. Install dependencies
pip install -r requirements.txt

# 3. Verify installation
python comic_library.py --help
```

Optional but Recommended:

· README.md - Full documentation
· example_config.ini - Configuration examples
· setup.sh - Automated setup script (Linux/Mac)

---

Quick Reference Card

5-Minute Setup:

```bash
# 1. Download files
mkdir ~/comic-tools && cd ~/comic-tools
# [Download comic_library.py and requirements.txt here]

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create config
python comic_library.py --directory ~/Comics --create-config

# 4. Edit config.ini (adjust settings)

# 5. Dry run
python comic_library.py --config ~/Comics/config.ini --dry-run

# 6. Process
python comic_library.py --config ~/Comics/config.ini
```

Essential Commands:

```bash
# Check help
python comic_library.py --help

# Create config
python comic_library.py --directory /comics --create-config

# Test run
python comic_library.py --config /comics/config.ini --dry-run --log-level INFO

# Full processing
python comic_library.py --config /comics/config.ini --workers 8

# View report
cat /comics/processing_report.json | python -m json.tool
```

---

Need Help?

Check the logs:

· Console output shows immediate feedback
· Log file (if configured) has detailed information
· JSON report contains complete change history

Test First:

Always test with --dry-run and a small subset of files before processing your entire library.

Backup First:

The script creates backups by default, but consider making a full backup of your comics folder before running for the first time.

---

That's it! You're ready to standardize your comic library. Start with a dry run, review the changes, then process your library with confidence.
