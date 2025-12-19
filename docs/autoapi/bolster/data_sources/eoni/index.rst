bolster.data_sources.eoni
=========================

.. py:module:: bolster.data_sources.eoni

.. autoapi-nested-parse::

   Working with Election Office NI Data

   The bits that we can; this module is primarily concerned with the ingestion of NI Assembly election results from 2003
   onwards (where possible in a vaguely reliable automated way)

   Hitlist:
   [X] 2022
   [X] 2017
   [X] 2016
   [ ] 2011
   [ ] 2007
   [ ] 2003



Functions
---------

.. autoapisummary::

   bolster.data_sources.eoni.get_page
   bolster.data_sources.eoni.find_xls_links_in_page
   bolster.data_sources.eoni.normalise_constituencies
   bolster.data_sources.eoni.get_metadata_from_df
   bolster.data_sources.eoni.get_candidates_from_df
   bolster.data_sources.eoni.get_stage_votes_from_df
   bolster.data_sources.eoni.get_stage_transfers_from_df
   bolster.data_sources.eoni.extract_stage_n_votes
   bolster.data_sources.eoni.extract_stage_n_transfers
   bolster.data_sources.eoni.get_results_from_sheet
   bolster.data_sources.eoni.get_results


Module Contents
---------------

.. py:function:: get_page(path)

   For a given path (within EONI.org.uk), get the response as a BeautifulSoup instance

   .. note:: EONI is trying to block people from scraping and will return a 403 error if you don't pass a 'conventional' user agent

   >>> page = get_page("/Elections/")
   >>> page.find('title').contents[0].strip()
   'Elections | The Electoral Office for Northern Ireland'



.. py:function:: find_xls_links_in_page(page)

   Walk through a BeautifulSoup page and iterate through '(XLS)' suffixed links

   (Primarily Used for 'Results' pages within given elections)

   #WTF Was starting to do some consistency checks between elections to make sure all is kosher, and was wondering why I had a Strangford listing in 2017 but not 2022;
   # As a cross-check on the result page, I walk the links in the right colum of the page, looking for links that have text that ends (XLS). Pretty simple you might think. Except the Strangford link ends in (XLS  and then a random closing ) text string is added to the end.

   >>> page = get_page("/results-data/ni-assembly-election-2022-results/")
   >>> len(list(find_xls_links_in_page(page)))
   18
   >>> next(find_xls_links_in_page(page))
   'https://www.eoni.org.uk/media/omtlpqow/ni-assembly-election-2022-result-sheet-belfast-east-xls.xlsx'



.. py:function:: normalise_constituencies(cons_str)

   Some constituencies change names or cases etc;

   Use this function to take external/unconventional inputs and project them into a normalised format

   >>> normalise_constituencies('Newry & Armagh')
   'newry and armagh'



.. py:function:: get_metadata_from_df(df)

   Extract Ballot metadata from the table header(s) of an XLS formatted result sheet, as output from `get_excel_dataframe`

   # TODO this could probably be done better as a `dataclass`

   :returns:

             dict of
                 'stage': int,
                 'date': datetime
                 'constituency': str (lower)
                 'eligible_electorate': int
                 'votes_polled': int
                 'number_to_be_elected': int
                 'invalid_votes': int
                 'electoral_quota': int


.. py:function:: get_candidates_from_df(df)

   Extract Candidates name and party columns from first stage sheet


.. py:function:: get_stage_votes_from_df(df)

   Extract the votes from each stage as a mapped column for each stage, i.e. stages 1...N


.. py:function:: get_stage_transfers_from_df(df)

   Extract the transfers from each stage as a mapped column for each stage, i.e. stages 2...N


.. py:function:: extract_stage_n_votes(df, n)

   Extract the votes from a given stage N

   Note: This will include trailing, unaligned `Nones` which must be cleaned up at the Ballot level


.. py:function:: extract_stage_n_transfers(df, n)

   Extract the votes from a given stage N

   Note: This will include trailing, unaligned `Nones` which must be cleaned up at the Ballot level
   Stage Transfers are associated with the 'next' stage, i.e. stage 1 has no transfers


.. py:function:: get_results_from_sheet(sheet_url)

.. py:function:: get_results(year)
