#!/usr/bin/env python3
"""
Comic Library Archive Standardizer v1.0
Converts all comic archives to CBZ format with proper naming based on config.ini
"""

import os
import sys
import argparse
import logging
import configparser
import json
import zipfile
import rarfile
import hashlib
import time
import signal
import csv
import shutil
import tempfile
from datetime import datetime
from pathlib import Path, PurePath
from typing import Dict, List, Tuple, Optional, Set, Any, Union
from dataclasses import dataclass, field, asdict
from enum import Enum, IntEnum
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
import traceback
from collections import defaultdict, Counter
import fnmatch
import re

# Constants
DEFAULT_WORKERS = min(8, multiprocessing.cpu_count())
VALID_EXTENSIONS = {'.cbz', '.cbr', '.zip', '.rar'}
CBZ_EXTENSION = '.cbz'
CBR_EXTENSION = '.cbr'
METADATA_FILENAME = "series.json"
CONFIG_FILENAME = "config.ini"

class ArchiveType(Enum):
    """Detected archive type"""
    ZIP = "zip"
    RAR = "rar"
    UNKNOWN = "unknown"

class ActionType(Enum):
    """Actions performed on files"""
    RENAMED = "renamed"
    CONVERTED = "converted"
    DELETED = "deleted"
    KEPT = "kept"
    SKIPPED = "skipped"
    ERROR = "error"

class ValidationResult(Enum):
    """Validation result"""
    VALID = "valid"
    INVALID = "invalid"
    CORRUPTED = "corrupted"
    MISNAMED = "misnamed"
    DUPLICATE = "duplicate"

@dataclass
class ArchiveInfo:
    """Information about an archive file"""
    path: Path
    size: int
    actual_type: ArchiveType
    extension: str
    file_count: int = 0
    checksum: Optional[str] = None
    last_modified: float = field(default_factory=time.time)
    newest_file_date: Optional[float] = None
    
    @property
    def expected_extension(self) -> str:
        """Get the expected extension based on actual type"""
        return CBZ_EXTENSION if self.actual_type == ArchiveType.ZIP else CBR_EXTENSION
    
    @property
    def is_misnamed(self) -> bool:
        """Check if file has wrong extension"""
        if self.actual_type == ArchiveType.UNKNOWN:
            return False
        expected = self.expected_extension
        return self.path.suffix.lower() != expected
    
    @property
    def needs_conversion(self) -> bool:
        """Check if file needs conversion (RAR to ZIP)"""
        return self.actual_type == ArchiveType.RAR
    
    def to_dict(self) -> Dict:
        return {
            'path': str(self.path),
            'name': self.path.name,
            'size': self.size,
            'actual_type': self.actual_type.value,
            'extension': self.extension,
            'expected_extension': self.expected_extension,
            'is_misnamed': self.is_misnamed,
            'needs_conversion': self.needs_conversion,
            'file_count': self.file_count,
            'checksum': self.checksum,
            'newest_file_date': datetime.fromtimestamp(self.newest_file_date).isoformat() 
                              if self.newest_file_date else None
        }

@dataclass
class Action:
    """Action performed on a file"""
    action_type: ActionType
    source: Path
    target: Optional[Path] = None
    reason: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict:
        return {
            'action': self.action_type.value,
            'source': str(self.source),
            'target': str(self.target) if self.target else None,
            'reason': self.reason,
            'details': self.details,
            'timestamp': datetime.fromtimestamp(self.timestamp).isoformat()
        }

@dataclass
class LibraryStats:
    """Statistics for the library processing"""
    total_files: int = 0
    processed_files: int = 0
    cbz_files: int = 0
    cbr_files: int = 0
    misnamed_files: int = 0
    converted_files: int = 0
    renamed_files: int = 0
    deleted_files: int = 0
    error_files: int = 0
    total_size: int = 0
    start_time: float = field(default_factory=time.time)
    end_time: float = 0
    
    def duration(self) -> float:
        return (self.end_time or time.time()) - self.start_time
    
    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            'duration': self.duration(),
            'processing_rate': self.processed_files / self.duration() if self.duration() > 0 else 0,
            'size_processed_mb': self.total_size / (1024 * 1024)
        }

class LibraryConfig:
    """Library configuration from config.ini"""
    
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.destination_dir: Optional[Path] = None
        self.folder_format: Optional[str] = None
        self.file_format: Optional[str] = None
        self.backup_files: bool = True
        self.dry_run: bool = False
        self.workers: int = DEFAULT_WORKERS
        self.log_level: str = 'INFO'
        self.log_file: Optional[Path] = None
        self.report_file: Optional[Path] = None
        
        self._load_config()
    
    def _load_config(self):
        """Load configuration from INI file"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        
        config = configparser.ConfigParser()
        config.read(self.config_path)
        
        # General section
        if 'General' in config:
            general = config['General']
            self.destination_dir = Path(general.get('destination_dir', '.')).expanduser().resolve()
            self.folder_format = general.get('folder_format', '{publisher}/{series}')
            self.file_format = general.get('file_format', '{series} v{volume:02d}')
        
        # Processing section
        if 'Processing' in config:
            proc = config['Processing']
            self.backup_files = proc.getboolean('backup_files', True)
            self.dry_run = proc.getboolean('dry_run', False)
            self.workers = proc.getint('workers', DEFAULT_WORKERS)
        
        # Output section
        if 'Output' in config:
            out = config['Output']
            self.log_level = out.get('log_level', 'INFO')
            if 'log_file' in out:
                self.log_file = Path(out.get('log_file')).expanduser()
            if 'report_file' in out:
                self.report_file = Path(out.get('report_file')).expanduser()
    
    def parse_folder_structure(self, publisher: str, series: str) -> str:
        """Generate folder path based on folder_format"""
        try:
            return self.folder_format.format(
                publisher=publisher,
                series=series,
                PUBLISHER=publisher.upper(),
                SERIES=series.upper()
            )
        except (KeyError, ValueError):
            # Fallback to default format
            return f"{publisher}/{series}"
    
    def parse_filename(self, series: str, volume: int, **kwargs) -> str:
        """Generate filename based on file_format"""
        try:
            return self.file_format.format(
                series=series,
                volume=volume,
                SERIES=series.upper(),
                **kwargs
            )
        except (KeyError, ValueError):
            # Fallback to default format
            return f"{series} v{volume:02d}"
    
    def to_dict(self) -> Dict:
        return {
            'config_path': str(self.config_path),
            'destination_dir': str(self.destination_dir),
            'folder_format': self.folder_format,
            'file_format': self.file_format,
            'backup_files': self.backup_files,
            'dry_run': self.dry_run,
            'workers': self.workers,
            'log_level': self.log_level,
            'log_file': str(self.log_file) if self.log_file else None,
            'report_file': str(self.report_file) if self.report_file else None
        }

class ArchiveAnalyzer:
    """Analyze archive files to determine type and contents"""
    
    @staticmethod
    def detect_archive_type(file_path: Path) -> ArchiveType:
        """Detect the actual archive type using file signatures"""
        try:
            # Read first few bytes to check signature
            with open(file_path, 'rb') as f:
                header = f.read(8)
            
            # Check for ZIP signature (PK\x03\x04 or PK\x05\x06 for empty zip)
            if header[:4] == b'PK\x03\x04' or header[:4] == b'PK\x05\x06':
                return ArchiveType.ZIP
            
            # Check for RAR signature (Rar!\x1a\x07\x00 or Rar!\x1a\x07\x01)
            if header[:7] == b'Rar!\x1a\x07':
                return ArchiveType.RAR
            
            # Try opening with zipfile
            try:
                with zipfile.ZipFile(file_path, 'r'):
                    return ArchiveType.ZIP
            except:
                pass
            
            # Try opening with rarfile
            try:
                with rarfile.RarFile(file_path, 'r'):
                    return ArchiveType.RAR
            except:
                pass
            
            return ArchiveType.UNKNOWN
            
        except Exception:
            return ArchiveType.UNKNOWN
    
    @staticmethod
    def analyze_archive(file_path: Path) -> Optional[ArchiveInfo]:
        """Analyze archive file and return info"""
        try:
            if not file_path.exists():
                return None
            
            size = file_path.stat().st_size
            actual_type = ArchiveAnalyzer.detect_archive_type(file_path)
            extension = file_path.suffix.lower()
            
            # Get file count and newest file date
            file_count = 0
            newest_date = None
            
            if actual_type == ArchiveType.ZIP:
                try:
                    with zipfile.ZipFile(file_path, 'r') as zf:
                        file_count = len(zf.namelist())
                        for info in zf.infolist():
                            # Convert datetime tuple to timestamp
                            dt = info.date_time
                            if dt:
                                file_date = datetime(dt[0], dt[1], dt[2], dt[3], dt[4], dt[5]).timestamp()
                                if newest_date is None or file_date > newest_date:
                                    newest_date = file_date
                except:
                    pass
            
            elif actual_type == ArchiveType.RAR:
                try:
                    with rarfile.RarFile(file_path, 'r') as rf:
                        file_count = len(rf.namelist())
                        for info in rf.infolist():
                            if info.mtime:
                                if newest_date is None or info.mtime > newest_date:
                                    newest_date = info.mtime
                except:
                    pass
            
            # Calculate checksum (fast xxhash if available)
            checksum = None
            try:
                if actual_type != ArchiveType.UNKNOWN:
                    checksum = ArchiveAnalyzer.calculate_checksum(file_path)
            except:
                pass
            
            return ArchiveInfo(
                path=file_path,
                size=size,
                actual_type=actual_type,
                extension=extension,
                file_count=file_count,
                checksum=checksum,
                last_modified=file_path.stat().st_mtime,
                newest_file_date=newest_date
            )
            
        except Exception as e:
            logging.error(f"Error analyzing {file_path}: {str(e)}")
            return None
    
    @staticmethod
    def calculate_checksum(file_path: Path, algorithm: str = 'xxh64') -> str:
        """Calculate file checksum"""
        try:
            if algorithm == 'xxh64':
                try:
                    import xxhash
                    hasher = xxhash.xxh64()
                except ImportError:
                    algorithm = 'md5'
                    hasher = hashlib.md5()
            elif algorithm == 'md5':
                hasher = hashlib.md5()
            elif algorithm == 'sha256':
                hasher = hashlib.sha256()
            else:
                hasher = hashlib.md5()
            
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    hasher.update(chunk)
            
            return f"{algorithm}:{hasher.hexdigest()}"
        except Exception:
            return "error"
    
    @staticmethod
    def compare_archives(archive1: ArchiveInfo, archive2: ArchiveInfo) -> int:
        """
        Compare two archives. Returns:
        -1: archive1 is better
         0: equal (tie)
         1: archive2 is better
        """
        # Compare file count
        if archive1.file_count > archive2.file_count:
            return -1
        elif archive1.file_count < archive2.file_count:
            return 1
        
        # Equal file count, compare newest file date
        if archive1.newest_file_date and archive2.newest_file_date:
            if archive1.newest_file_date > archive2.newest_file_date:
                return -1
            elif archive1.newest_file_date < archive2.newest_file_date:
                return 1
        
        # Still equal, compare size (larger might have better quality)
        if archive1.size > archive2.size:
            return -1
        elif archive1.size < archive2.size:
            return 1
        
        return 0  # Tie

class ArchiveConverter:
    """Convert RAR archives to ZIP format"""
    
    @staticmethod
    def convert_rar_to_zip(rar_path: Path, zip_path: Path) -> bool:
        """Convert RAR archive to ZIP format"""
        temp_dir = None
        try:
            # Create temporary directory for extraction
            temp_dir = Path(tempfile.mkdtemp(prefix="cbz_convert_"))
            
            # Extract RAR
            with rarfile.RarFile(rar_path, 'r') as rf:
                rf.extractall(temp_dir)
            
            # Create ZIP
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for file in temp_dir.rglob('*'):
                    if file.is_file():
                        # Preserve directory structure
                        arcname = file.relative_to(temp_dir)
                        zf.write(file, arcname)
            
            # Verify the ZIP was created correctly
            if zip_path.exists():
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    # Quick test
                    test_file = zf.namelist()[0] if zf.namelist() else None
                    if test_file:
                        zf.read(test_file, 1024)  # Read first 1KB
                
                return True
            
            return False
            
        except Exception as e:
            logging.error(f"Error converting {rar_path} to ZIP: {str(e)}")
            # Clean up failed conversion
            if zip_path.exists():
                try:
                    zip_path.unlink()
                except:
                    pass
            return False
            
        finally:
            # Clean up temp directory
            if temp_dir and temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                except:
                    pass
    
    @staticmethod
    def backup_file(file_path: Path) -> Optional[Path]:
        """Create a backup of a file"""
        try:
            backup_path = file_path.with_suffix(file_path.suffix + '.bak')
            counter = 1
            while backup_path.exists():
                backup_path = file_path.with_suffix(f"{file_path.suffix}.bak.{counter}")
                counter += 1
            
            shutil.copy2(file_path, backup_path)
            return backup_path
        except Exception as e:
            logging.error(f"Failed to backup {file_path}: {str(e)}")
            return None

class ComicLibraryManager:
    """Main class for managing comic library"""
    
    def __init__(self, config: LibraryConfig):
        self.config = config
        self.library_root = config.destination_dir
        self.actions: List[Action] = []
        self.stats = LibraryStats()
        self.duplicate_groups: Dict[str, List[ArchiveInfo]] = defaultdict(list)
        
        self._setup_logging()
        
        if not self.library_root or not self.library_root.exists():
            raise ValueError(f"Library root directory does not exist: {self.library_root}")
    
    def _setup_logging(self):
        """Setup logging configuration"""
        self.logger = logging.getLogger('ComicLibraryManager')
        self.logger.setLevel(getattr(logging, self.config.log_level.upper()))
        
        # Clear existing handlers
        self.logger.handlers.clear()
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_format = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_format)
        self.logger.addHandler(console_handler)
        
        # File handler if specified
        if self.config.log_file:
            self.config.log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(self.config.log_file, mode='a', encoding='utf-8')
            file_handler.setFormatter(console_format)
            self.logger.addHandler(file_handler)
        
        self.logger.info(f"Comic Library Manager initialized")
        self.logger.info(f"Library root: {self.library_root}")
        self.logger.info(f"Dry run: {self.config.dry_run}")
        self.logger.info(f"Workers: {self.config.workers}")
    
    def scan_library(self) -> List[ArchiveInfo]:
        """Scan library for all comic archive files"""
        self.logger.info(f"Scanning library at: {self.library_root}")
        
        archive_files = []
        
        # Walk through all directories
        for root, dirs, files in os.walk(self.library_root):
            # Skip backup directories
            if any(x in root.lower() for x in ['backup', 'trash', 'temp', '.tmp']):
                continue
            
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix.lower() in VALID_EXTENSIONS:
                    archive_files.append(file_path)
        
        self.stats.total_files = len(archive_files)
        self.logger.info(f"Found {self.stats.total_files} archive files")
        
        return archive_files
    
    def analyze_files(self, file_paths: List[Path]) -> List[ArchiveInfo]:
        """Analyze files in parallel"""
        self.logger.info(f"Analyzing {len(file_paths)} files...")
        
        archives = []
        
        if self.config.workers > 1 and len(file_paths) > 1:
            # Parallel analysis
            with ProcessPoolExecutor(max_workers=self.config.workers) as executor:
                future_to_file = {
                    executor.submit(ArchiveAnalyzer.analyze_archive, file_path): file_path
                    for file_path in file_paths
                }
                
                for future in as_completed(future_to_file):
                    file_path = future_to_file[future]
                    try:
                        archive_info = future.result()
                        if archive_info:
                            archives.append(archive_info)
                            self._log_archive_info(archive_info)
                    except Exception as e:
                        self.logger.error(f"Error analyzing {file_path}: {str(e)}")
        else:
            # Sequential analysis
            for file_path in file_paths:
                archive_info = ArchiveAnalyzer.analyze_archive(file_path)
                if archive_info:
                    archives.append(archive_info)
                    self._log_archive_info(archive_info)
        
        return archives
    
    def _log_archive_info(self, archive_info: ArchiveInfo):
        """Log information about an archive"""
        if archive_info.actual_type == ArchiveType.UNKNOWN:
            self.logger.warning(f"❓ Unknown type: {archive_info.path.name}")
        elif archive_info.is_misnamed:
            self.logger.warning(f"⚠ Misnamed: {archive_info.path.name} (actual: {archive_info.actual_type.value})")
        elif archive_info.needs_conversion:
            self.logger.info(f"🔄 Needs conversion: {archive_info.path.name}")
        else:
            self.logger.debug(f"✓ OK: {archive_info.path.name}")
    
    def find_duplicates(self, archives: List[ArchiveInfo]):
        """Find potential duplicate files (same name, different extensions)"""
        # Group by base name (without extension)
        name_groups = defaultdict(list)
        for archive in archives:
            if archive.actual_type != ArchiveType.UNKNOWN:
                base_name = archive.path.stem.lower()
                name_groups[base_name].append(archive)
        
        # Find groups with multiple files
        for base_name, group in name_groups.items():
            if len(group) > 1:
                # Check if they have different extensions
                extensions = {a.path.suffix.lower() for a in group}
                if len(extensions) > 1:
                    self.duplicate_groups[base_name] = group
                    self.logger.warning(f"Found {len(group)} files with name '{base_name}': {[a.path.name for a in group]}")
    
    def process_archive(self, archive_info: ArchiveInfo) -> List[Action]:
        """Process a single archive file"""
        actions = []
        
        try:
            # Skip unknown archive types
            if archive_info.actual_type == ArchiveType.UNKNOWN:
                actions.append(Action(
                    action_type=ActionType.SKIPPED,
                    source=archive_info.path,
                    reason="Unknown archive type"
                ))
                return actions
            
            # Determine target path
            target_path = self._get_target_path(archive_info)
            
            # Check for duplicates
            duplicate_action = self._handle_duplicates(archive_info, target_path)
            if duplicate_action:
                actions.append(duplicate_action)
                return actions
            
            # Check if file needs renaming or conversion
            if archive_info.is_misnamed or archive_info.needs_conversion:
                # Create backup if configured
                if self.config.backup_files and not self.config.dry_run:
                    backup_path = ArchiveConverter.backup_file(archive_info.path)
                    if backup_path:
                        actions.append(Action(
                            action_type=ActionType.KEPT,
                            source=archive_info.path,
                            target=backup_path,
                            reason="Backup created before modification"
                        ))
                
                if archive_info.needs_conversion:
                    # Convert RAR to ZIP
                    if not self.config.dry_run:
                        success = ArchiveConverter.convert_rar_to_zip(archive_info.path, target_path)
                        if success:
                            actions.append(Action(
                                action_type=ActionType.CONVERTED,
                                source=archive_info.path,
                                target=target_path,
                                reason="Converted RAR to ZIP format",
                                details={'original_size': archive_info.size, 'file_count': archive_info.file_count}
                            ))
                            # Delete original after successful conversion
                            try:
                                archive_info.path.unlink()
                                actions.append(Action(
                                    action_type=ActionType.DELETED,
                                    source=archive_info.path,
                                    reason="Original deleted after conversion"
                                ))
                            except Exception as e:
                                actions.append(Action(
                                    action_type=ActionType.ERROR,
                                    source=archive_info.path,
                                    reason=f"Failed to delete original: {str(e)}"
                                ))
                        else:
                            actions.append(Action(
                                action_type=ActionType.ERROR,
                                source=archive_info.path,
                                reason="Conversion failed"
                            ))
                    else:
                        actions.append(Action(
                            action_type=ActionType.CONVERTED,
                            source=archive_info.path,
                            target=target_path,
                            reason="[DRY RUN] Would convert RAR to ZIP"
                        ))
                
                elif archive_info.is_misnamed:
                    # Just rename the file
                    if not self.config.dry_run:
                        try:
                            archive_info.path.rename(target_path)
                            actions.append(Action(
                                action_type=ActionType.RENAMED,
                                source=archive_info.path,
                                target=target_path,
                                reason=f"Fixed misnamed extension (was {archive_info.extension})"
                            ))
                        except Exception as e:
                            actions.append(Action(
                                action_type=ActionType.ERROR,
                                source=archive_info.path,
                                reason=f"Failed to rename: {str(e)}"
                            ))
                    else:
                        actions.append(Action(
                            action_type=ActionType.RENAMED,
                            source=archive_info.path,
                            target=target_path,
                            reason=f"[DRY RUN] Would rename (was {archive_info.extension})"
                        ))
            else:
                # File is already correct
                actions.append(Action(
                    action_type=ActionType.KEPT,
                    source=archive_info.path,
                    reason="Already in correct format"
                ))
            
        except Exception as e:
            actions.append(Action(
                action_type=ActionType.ERROR,
                source=archive_info.path,
                reason=f"Processing error: {str(e)}"
            ))
            self.logger.error(f"Error processing {archive_info.path}: {str(e)}")
        
        return actions
    
    def _get_target_path(self, archive_info: ArchiveInfo) -> Path:
        """Determine target path for an archive"""
        # Extract metadata from filename for folder structure
        publisher = "Unknown"
        series = "Unknown"
        volume = 1
        
        # Try to extract from path structure
        parts = archive_info.path.relative_to(self.library_root).parts
        if len(parts) >= 2:
            publisher = parts[0]
            series = parts[1]
        
        # Try to extract volume number from filename
        filename = archive_info.path.stem
        volume_match = re.search(r'v(\d+)', filename, re.IGNORECASE)
        if volume_match:
            try:
                volume = int(volume_match.group(1))
            except:
                pass
        else:
            # Look for other volume patterns
            for pattern in [r'#(\d+)', r'issue\s*(\d+)', r'(\d{2,})']:
                match = re.search(pattern, filename)
                if match:
                    try:
                        volume = int(match.group(1))
                        break
                    except:
                        continue
        
        # Generate folder structure
        folder_structure = self.config.parse_folder_structure(publisher, series)
        folder_path = self.library_root / folder_structure
        
        # Generate filename
        filename_base = self.config.parse_filename(series, volume, publisher=publisher)
        target_filename = f"{filename_base}{CBZ_EXTENSION}"
        
        # Ensure unique filename
        target_path = folder_path / target_filename
        counter = 1
        while target_path.exists():
            target_filename = f"{filename_base}_{counter}{CBZ_EXTENSION}"
            target_path = folder_path / target_filename
            counter += 1
        
        return target_path
    
    def _handle_duplicates(self, archive_info: ArchiveInfo, target_path: Path) -> Optional[Action]:
        """Handle duplicate files (same target path)"""
        if target_path.exists():
            # Analyze existing file
            existing_info = ArchiveAnalyzer.analyze_archive(target_path)
            if existing_info and existing_info.actual_type != ArchiveType.UNKNOWN:
                # Compare archives
                comparison = ArchiveAnalyzer.compare_archives(archive_info, existing_info)
                
                if comparison < 0:
                    # New file is better, replace existing
                    if not self.config.dry_run:
                        # Backup existing file
                        if self.config.backup_files:
                            ArchiveConverter.backup_file(target_path)
                        # Delete existing
                        try:
                            target_path.unlink()
                        except:
                            pass
                    
                    self.logger.warning(f"Replacing {target_path.name} with better version")
                    return Action(
                        action_type=ActionType.DELETED if not self.config.dry_run else ActionType.SKIPPED,
                        source=target_path,
                        reason=f"Replaced by better version (files: {archive_info.file_count} > {existing_info.file_count})"
                    )
                else:
                    # Existing file is better or equal, skip new file
                    self.logger.warning(f"Skipping {archive_info.path.name}, keeping existing {target_path.name}")
                    return Action(
                        action_type=ActionType.SKIPPED,
                        source=archive_info.path,
                        reason=f"Duplicate, existing file is better or equal (files: {existing_info.file_count} >= {archive_info.file_count})"
                    )
        
        return None
    
    def process_all(self) -> List[Action]:
        """Process all archive files in the library"""
        self.logger.info("Starting library processing...")
        
        # Scan for files
        file_paths = self.scan_library()
        
        # Analyze files
        archives = self.analyze_files(file_paths)
        
        # Find duplicates
        self.find_duplicates(archives)
        
        # Process each archive
        all_actions = []
        
        for archive_info in archives:
            actions = self.process_archive(archive_info)
            all_actions.extend(actions)
            
            # Update statistics
            self.stats.processed_files += 1
            self.stats.total_size += archive_info.size
            
            for action in actions:
                if action.action_type == ActionType.CONVERTED:
                    self.stats.converted_files += 1
                elif action.action_type == ActionType.RENAMED:
                    self.stats.renamed_files += 1
                elif action.action_type == ActionType.DELETED:
                    self.stats.deleted_files += 1
                elif action.action_type == ActionType.ERROR:
                    self.stats.error_files += 1
                
                # Log the action
                if action.action_type != ActionType.KEPT:
                    self.logger.info(f"{action.action_type.value.upper()}: {action.source.name} -> {action.target.name if action.target else 'N/A'}")
                    if action.reason:
                        self.logger.debug(f"  Reason: {action.reason}")
        
        # Count final format distribution
        cbz_count = 0
        cbr_count = 0
        for root, dirs, files in os.walk(self.library_root):
            for file in files:
                if file.endswith(CBZ_EXTENSION):
                    cbz_count += 1
                elif file.endswith(CBR_EXTENSION):
                    cbr_count += 1
        
        self.stats.cbz_files = cbz_count
        self.stats.cbr_files = cbr_count
        
        self.stats.end_time = time.time()
        self.actions = all_actions
        
        return all_actions
    
    def generate_report(self, output_path: Optional[Path] = None) -> Dict:
        """Generate comprehensive report"""
        if output_path is None and self.config.report_file:
            output_path = self.config.report_file
        
        # Group actions by type
        actions_by_type = defaultdict(list)
        for action in self.actions:
            actions_by_type[action.action_type.value].append(action.to_dict())
        
        report = {
            'summary': {
                'library_root': str(self.library_root),
                'timestamp': datetime.now().isoformat(),
                'configuration': self.config.to_dict(),
                'statistics': self.stats.to_dict(),
                'final_state': {
                    'cbz_files': self.stats.cbz_files,
                    'cbr_files': self.stats.cbr_files,
                    'total_archives': self.stats.cbz_files + self.stats.cbr_files
                }
            },
            'actions': dict(actions_by_type),
            'duplicates': {
                group_name: [a.to_dict() for a in archives]
                for group_name, archives in self.duplicate_groups.items()
            },
            'issues': self._generate_issue_report()
        }
        
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            if output_path.suffix.lower() == '.json':
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(report, f, indent=2, ensure_ascii=False)
                self.logger.info(f"JSON report saved to: {output_path}")
            elif output_path.suffix.lower() == '.csv':
                self._generate_csv_report(output_path, report)
            else:
                # Default to JSON
                with open(output_path.with_suffix('.json'), 'w', encoding='utf-8') as f:
                    json.dump(report, f, indent=2, ensure_ascii=False)
                self.logger.info(f"JSON report saved to: {output_path.with_suffix('.json')}")
        
        return report
    
    def _generate_issue_report(self) -> Dict:
        """Generate report of issues found"""
        issues = {
            'misnamed_files': [],
            'corrupted_files': [],
            'duplicate_files': [],
            'conversion_errors': []
        }
        
        for action in self.actions:
            if action.action_type == ActionType.ERROR:
                if 'conversion' in action.reason.lower():
                    issues['conversion_errors'].append(action.to_dict())
                else:
                    issues['corrupted_files'].append(action.to_dict())
            elif action.action_type == ActionType.RENAMED and 'misnamed' in action.reason.lower():
                issues['misnamed_files'].append(action.to_dict())
        
        for group_name, archives in self.duplicate_groups.items():
            issues['duplicate_files'].append({
                'base_name': group_name,
                'files': [a.path.name for a in archives],
                'resolutions': [
                    a.to_dict() for a in self.actions 
                    if a.source in [arc.path for arc in archives]
                ]
            })
        
        return issues
    
    def _generate_csv_report(self, output_path: Path, report: Dict):
        """Generate CSV report"""
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Write summary
            writer.writerow(['Summary'])
            writer.writerow(['Library Root', report['summary']['library_root']])
            writer.writerow(['Timestamp', report['summary']['timestamp']])
            
            stats = report['summary']['statistics']
            writer.writerow([])
            writer.writerow(['Statistics'])
            writer.writerow(['Total Files', stats['total_files']])
            writer.writerow(['Processed Files', stats['processed_files']])
            writer.writerow(['Converted Files', stats['converted_files']])
            writer.writerow(['Renamed Files', stats['renamed_files']])
            writer.writerow(['Deleted Files', stats['deleted_files']])
            writer.writerow(['Error Files', stats['error_files']])
            writer.writerow(['Final CBZ Files', report['summary']['final_state']['cbz_files']])
            writer.writerow(['Final CBR Files', report['summary']['final_state']['cbr_files']])
            writer.writerow(['Duration (seconds)', stats['duration']])
            
            # Write actions
            writer.writerow([])
            writer.writerow(['Actions'])
            writer.writerow(['Type', 'Source', 'Target', 'Reason', 'Timestamp'])
            
            for action_type, actions in report['actions'].items():
                for action in actions:
                    writer.writerow([
                        action_type,
                        action['source'],
                        action.get('target', ''),
                        action.get('reason', ''),
                        action.get('timestamp', '')
                    ])
    
    def print_summary(self):
        """Print summary to console"""
        print("\n" + "="*80)
        print(" " * 30 + "COMIC LIBRARY PROCESSING SUMMARY")
        print("="*80)
        
        print(f"\n📚 LIBRARY OVERVIEW")
        print(f"   Root directory:      {self.library_root}")
        print(f"   Total files found:   {self.stats.total_files:,}")
        print(f"   Files processed:     {self.stats.processed_files:,}")
        
        print(f"\n🔄 PROCESSING RESULTS")
        print(f"   Files converted:     {self.stats.converted_files:,} (RAR → ZIP)")
        print(f"   Files renamed:       {self.stats.renamed_files:,} (fixed extensions)")
        print(f"   Files deleted:       {self.stats.deleted_files:,} (duplicates/replacements)")
        print(f"   Processing errors:   {self.stats.error_files:,}")
        
        print(f"\n📊 FINAL STATE")
        print(f"   CBZ files:           {self.stats.cbz_files:,} (ZIP format)")
        print(f"   CBR files:           {self.stats.cbr_files:,} (RAR format)")
        
        print(f"\n⏱️  PERFORMANCE")
        print(f"   Duration:            {self.stats.duration():.2f} seconds")
        print(f"   Processing rate:     {self.stats.processed_files / self.stats.duration():.2f} files/sec" 
              if self.stats.duration() > 0 else "   Processing rate:     0 files/sec")
        
        # List issues if any
        if self.duplicate_groups:
            print(f"\n⚠️  DUPLICATE FILES FOUND")
            for group_name, archives in list(self.duplicate_groups.items())[:5]:
                print(f"   {group_name}: {len(archives)} versions")
            if len(self.duplicate_groups) > 5:
                print(f"   ... and {len(self.duplicate_groups) - 5} more duplicate groups")
        
        error_actions = [a for a in self.actions if a.action_type == ActionType.ERROR]
        if error_actions:
            print(f"\n❌ PROCESSING ERRORS")
            for action in error_actions[:3]:
                print(f"   {action.source.name}: {action.reason}")
            if len(error_actions) > 3:
                print(f"   ... and {len(error_actions) - 3} more errors")
        
        if self.config.dry_run:
            print(f"\n⚠️  DRY RUN - No files were modified")
        
        print("\n" + "="*80)

def create_default_config(config_path: Path, library_root: Path):
    """Create a default configuration file"""
    config = configparser.ConfigParser()
    
    config['General'] = {
        'destination_dir': str(library_root.resolve()),
        'folder_format': '{publisher}/{series}',
        'file_format': '{series} v{volume:02d}'
    }
    
    config['Processing'] = {
        'backup_files': 'yes',
        'dry_run': 'no',
        'workers': str(DEFAULT_WORKERS)
    }
    
    config['Output'] = {
        'log_level': 'INFO',
        'log_file': str(library_root / 'library_processing.log'),
        'report_file': str(library_root / 'processing_report.json')
    }
    
    with open(config_path, 'w') as f:
        config.write(f)
    
    print(f"Default configuration created at: {config_path}")
    print("\nConfiguration options:")
    print("  [General]")
    print("    destination_dir = Path to your comic library")
    print("    folder_format   = Directory structure (use {publisher} and {series} variables)")
    print("    file_format     = File naming (use {series}, {volume}, {publisher} variables)")
    print("\n  [Processing]")
    print("    backup_files    = Create backups before modifying files (yes/no)")
    print("    dry_run         = Simulate changes without modifying files (yes/no)")
    print("    workers         = Number of parallel workers")
    print("\n  [Output]")
    print("    log_level       = DEBUG, INFO, WARNING, ERROR")
    print("    log_file        = Path to log file")
    print("    report_file     = Path to JSON report file")

def main():
    """Main entry point"""
    signal.signal(signal.SIGINT, lambda s, f: (print("\n\nInterrupted by user"), sys.exit(1)))
    
    parser = argparse.ArgumentParser(
        description="Comic Library Archive Standardizer - Convert all files to CBZ format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --config config.ini
  %(prog)s --directory /comics/library --create-config
  %(prog)s --config config.ini --dry-run --log-level DEBUG
  %(prog)s --config config.ini --no-backup --workers 8

Directory Structure (based on config.ini):
  destination_dir/
    Publisher Name/
      Series Name/
        Series Name v01.cbz
        Series Name v02.cbz
        ...
        
File Processing Rules:
  1. All .cbr (RAR) files will be converted to .cbz (ZIP)
  2. Misnamed files (.cbr that are actually ZIP, .cbz that are actually RAR) will be renamed
  3. If renaming creates a duplicate, the better file is kept (more files > newer files > larger size)
  4. Backups are created before modifications (configurable)
        """
    )
    
    parser.add_argument(
        '-c', '--config',
        type=Path,
        help='Configuration file (config.ini)'
    )
    
    parser.add_argument(
        '-d', '--directory',
        type=Path,
        help='Library directory (creates config if used with --create-config)'
    )
    
    parser.add_argument(
        '--create-config',
        action='store_true',
        help='Create a default configuration file and exit'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Simulate changes without modifying files'
    )
    
    parser.add_argument(
        '--no-backup',
        action='store_true',
        help='Disable backup creation'
    )
    
    parser.add_argument(
        '-w', '--workers',
        type=int,
        help=f'Override number of worker processes (default: {DEFAULT_WORKERS})'
    )
    
    parser.add_argument(
        '-l', '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Override logging level'
    )
    
    parser.add_argument(
        '--report',
        type=Path,
        help='Override report file location'
    )
    
    args = parser.parse_args()
    
    try:
        config = None
        
        if args.config:
            # Load configuration from file
            config = LibraryConfig(args.config)
            print(f"Loaded configuration from: {args.config}")
        
        elif args.directory:
            # Create temporary config from command line
            if not args.directory.exists():
                print(f"Error: Directory does not exist: {args.directory}")
                return 1
            
            # Create config file if requested
            if args.create_config:
                config_path = args.directory / CONFIG_FILENAME
                create_default_config(config_path, args.directory)
                print(f"\nPlease edit {config_path} and then run:")
                print(f"  {sys.argv[0]} --config {config_path}")
                return 0
            
            # Use default config with directory
            config_path = args.directory / CONFIG_FILENAME
            if not config_path.exists():
                print(f"Error: Config file not found: {config_path}")
                print(f"Use --create-config to create a default configuration")
                return 1
            
            config = LibraryConfig(config_path)
        
        else:
            parser.print_help()
            return 1
        
        # Override config with command line arguments
        if args.dry_run:
            config.dry_run = True
        
        if args.no_backup:
            config.backup_files = False
        
        if args.workers:
            config.workers = args.workers
        
        if args.log_level:
            config.log_level = args.log_level
        
        if args.report:
            config.report_file = args.report
        
        # Create and run manager
        manager = ComicLibraryManager(config)
        
        # Process library
        actions = manager.process_all()
        
        # Generate report
        if config.report_file or args.report:
            manager.generate_report()
        
        # Print summary
        manager.print_summary()
        
        # Return non-zero exit code if there were errors
        if manager.stats.error_files > 0:
            return 1
        
        return 0
        
    except Exception as e:
        print(f"Error: {str(e)}")
        if args.log_level == 'DEBUG' or (config and config.log_level == 'DEBUG'):
            traceback.print_exc()
        return 2

if __name__ == "__main__":
    sys.exit(main())

