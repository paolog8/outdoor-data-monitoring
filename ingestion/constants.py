import re

TRACKER_NAME       = "PeroCube"
TRACKER_MODEL      = "PeroCube"
SLOT_CODE_PATTERN  = "PC01_board{:02d}_channel{:02d}"
BOARDS             = range(1, 11)   # boards 1..10
CHANNELS           = range(1, 25)   # channels 1..24
DEFAULT_BATCH_SIZE = 1000
FOLDER_RE          = re.compile(r"^data_\d{8}$")
TEMP_FILE_RE       = re.compile(r"^m7004_ID_([0-9A-Fa-f]+)\.txt$")
IRRADIANCE_FILE_RE = re.compile(r"^PT-104_channel_(\d+)\.txt$")
SPECTRAL_FILE_RE   = re.compile(r"^\d{10}\.CSV$", re.IGNORECASE)
