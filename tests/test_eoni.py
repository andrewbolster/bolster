import datetime
import unittest

from bolster.data_sources.eoni import _headers, get_results, get_results_from_sheet
from bolster.utils.web import get_excel_dataframe

constituencies_post_2003 = {
    "belfast east",
    "belfast north",
    "belfast south",
    "belfast west",
    "east antrim",
    "east londonderry",
    "fermanagh and south tyrone",
    "foyle",
    "lagan valley",
    "mid ulster",
    "newry and armagh",
    "north antrim",
    "north down",
    "south antrim",
    "south down",
    "strangford",
    "upper bann",
    "west tyrone",
}

# Fixture for the URL to test
test_assembly_result_xls_url = (
    "https://www.eoni.org.uk/media/omtlpqow/ni-assembly-election-2022-result-sheet-belfast-east-xls.xlsx"
)


class MyTestCase(unittest.TestCase):
    def test_sheet_read(self):
        df = get_excel_dataframe(test_assembly_result_xls_url, requests_kwargs={"headers": _headers})
        self.assertEqual(df.shape, (231, 110))

    def test_sheet_metadata(self):
        test_metadata = {
            "stage": 12,
            "date": datetime.datetime(2022, 5, 5, 0, 0),
            "constituency": "belfast east",
            "eligible_electorate": 70123,
            "votes_polled": 43840,
            "number_to_be_elected": 5,
            "total_valid_votes": 43248,
            "invalid_votes": 592,
            "electoral_quota": 7209,
        }
        data = get_results_from_sheet(test_assembly_result_xls_url)
        self.assertDictEqual(data["metadata"], test_metadata)

    def test_2022_constituency_parsing(self):
        data = get_results(2022)
        self.assertSetEqual(set(data.keys()), constituencies_post_2003)

    @unittest.skip(
        reason="Not currently possible as 2017 results were nuked by EONI https://twitter.com/Bolster/status/1783446858859241775"
    )
    def test_2017_constituency_parsing(self):
        data = get_results(2017)
        self.assertSetEqual(set(data.keys()), constituencies_post_2003)

    @unittest.skip(
        reason="Not currently possible as 2016 results were nuked by EONI https://twitter.com/Bolster/status/1783446858859241775"
    )
    def test_2016_constituency_parsing(self):
        data = get_results(2016)
        self.assertSetEqual(set(data.keys()), constituencies_post_2003)

    @unittest.skip(reason="Not currently possible as 2011 results are presented as PDFs")
    def test_2011_constituency_parsing(self):
        data = get_results(2011)
        self.assertSetEqual(set(data.keys()), constituencies_post_2003)


if __name__ == "__main__":
    unittest.main()
