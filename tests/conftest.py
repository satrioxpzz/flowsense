import sys
from unittest.mock import MagicMock, patch

mock_psycopg = MagicMock()
mock_boto3 = MagicMock()

patch.dict("sys.modules", {"psycopg": mock_psycopg, "boto3": mock_boto3}).start()
