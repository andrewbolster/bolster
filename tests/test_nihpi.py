import unittest
from urllib.parse import urlparse

import requests_cache

from bolster.data_sources import ni_house_price_index as hpi


class MyTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        requests_cache.install_cache(expire_after=3600, allowable_methods=("GET",))

    def test_source(self):
        url = hpi.get_source_url()
        self.assertIsNotNone(url)
        parsed_url = urlparse(url)
        self.assertEqual(parsed_url.scheme, "https")
        self.assertEqual(parsed_url.netloc, "www.finance-ni.gov.uk")

    def test_source_size(self):
        dfs = hpi.pull_sources()
        self.assertEqual(len(dfs), 36)  # Source has changed size, should be 36 long!

    def test_output_size(self):
        dfs = hpi.build()
        self.assertEqual(len(dfs), 33)  # Final has changed size, should be 33

    @classmethod
    def tearDownClass(cls) -> None:
        requests_cache.clear()
        requests_cache.uninstall_cache()


if __name__ == "__main__":
    unittest.main()
