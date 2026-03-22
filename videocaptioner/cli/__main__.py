"""Allow running as: python -m videocaptioner.cli"""

import sys

from videocaptioner.cli.main import main

sys.exit(main())
