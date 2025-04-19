# TESTING NOTES

When fixing things, the below helps; and you keep forgetting it

```py
import sys
import os
from pathlib import Path

# Get the absolute path to the src directory
# Adjust this path as needed based on the location of your notebook
src_path = Path("../src").resolve()  # If scripts is at the same level as src
sys.path.insert(0, str(src_path))

import bolster
```
