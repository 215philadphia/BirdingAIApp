import os
import tempfile

# app.main builds a default app at import time; keep its data out of the repo.
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="birding-test-"))
