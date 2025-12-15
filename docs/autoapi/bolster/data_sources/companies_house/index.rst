bolster.data_sources.companies_house
====================================

.. py:module:: bolster.data_sources.companies_house


Functions
---------

.. autoapisummary::

   bolster.data_sources.companies_house.get_basic_company_data_url
   bolster.data_sources.companies_house.query_basic_company_data
   bolster.data_sources.companies_house.companies_house_record_might_be_farset
   bolster.data_sources.companies_house.get_companies_house_records_that_might_be_in_farset


Module Contents
---------------

.. py:function:: get_basic_company_data_url()

   Parse the companies house website to get the current URL for the 'BasicCompanyData'

   Currently uses the 'one file' method but it could be split into the multi files for memory efficiency


.. py:function:: query_basic_company_data(query_func = always)

   Grab the url for the basic company data, and walk through the CSV files within, and
   for each row in each CSV file, parse the row data through the given `query_func`
   such that if `query_func(row)` is True it will be yielded


.. py:function:: companies_house_record_might_be_farset(r)

   A heuristic function for working out if a record in the companies house registry *might* be based in Farset Labs
   Almost certainly incomplete and needs more testing/validation


.. py:function:: get_companies_house_records_that_might_be_in_farset()
