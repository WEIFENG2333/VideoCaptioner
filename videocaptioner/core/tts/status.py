from enum import Enum
from typing import Tuple


class TTSStatus(Enum):
    """TTS processing status with progress percentage.

    Each status contains a tuple of (message, progress_percentage).
    Progress ranges from 0 to 100.
    """

    # Initialization
    INITIALIZING = ("initializing", 0)
    PREPARING = ("preparing", 10)

    # Synthesis phase (20-90%)
    SYNTHESIZING = ("synthesizing", 30)
    PROCESSING = ("processing", 50)
    SAVING = ("saving", 70)

    # Completion phase (90-100%)
    FINALIZING = ("finalizing", 90)
    COMPLETED = ("completed", 100)

    @property
    def message(self) -> str:
        """Get the status message."""
        return self.value[0]

    @property
    def progress(self) -> int:
        """Get the progress percentage (0-100)."""
        return self.value[1]

    def with_progress(self, progress: int) -> Tuple[int, str]:
        """Create a callback tuple with custom progress.

        Args:
            progress: Progress percentage (0-100)

        Returns:
            Tuple of (progress, message) suitable for callback functions
        """
        return (progress, self.message)

    def callback_tuple(self) -> Tuple[int, str]:
        """Get the callback tuple (progress, message)."""
        return (self.progress, self.message)
