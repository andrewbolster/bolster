import logging

from itertools import zip_longest
from typing import Dict, Optional, AnyStr, List

from atlassian import Confluence as Confluence_Orig

from .html_tables import parse_table_data, make_html_table
from .. import diff

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class Confluence(Confluence_Orig):

    def post_html_report(self, space: AnyStr, pagename: AnyStr, data: List[Dict], cols: List, append: bool = False,
                         prepend=False, header=None, footer=None, new_index: Optional[List] = None):
        if header is None:
            header = ''
        if footer is None:
            footer = ''
        if new_index is None:
            new_index = [None for _ in data]

        if append and prepend:
            raise ValueError("Can't have both append and prepend!")

        if not isinstance(new_index, list):
            raise TypeError(f"Got new_index {new_index}, expected a list")

        if self.page_exists(space, pagename):
            old_page = self.get_page_by_title(space, pagename)
            old_page_body = self.get_page_by_id(old_page['id'], expand='body.storage')['body']['storage']['value']
            logger.info("Page exists")
            table = next(parse_table_data(old_page_body))

            # We know that the None is actually the 'index' column
            # Also we know the column order....

            table_index = [d[None] for d in table]

            table = [
                {k: v
                 for k, v in sorted(
                    d.items(), key=lambda _d: cols.index(_d[0]) if _d[0] in cols else len(cols)
                ) if k is not None}
                for d in table
            ]

            if append or prepend:
                # TODO how to do multi-value appends...
                if len(new_index) > 1:
                    raise ValueError("Can't append more than one row at a time, sorry!")
                if new_index[0] in table_index:
                    logger.info("That index row is already present")
                else:
                    logger.info(f"Gotta update to add {new_index} to {'end of ' if append else 'start of'} {table_index}")
                    new_table = make_html_table(table + data if append else data + table,
                                                keys=cols,
                                                indexer=lambda d: zip(table_index + new_index if append else
                                                                      new_index + table_index, d)
                                                )
                    page = header + new_table + footer
                    self.update_page(None, old_page['id'], old_page['title'], page, type='page')

            else:
                new_table = make_html_table(data, keys=cols, indexer=lambda d: zip(table_index + new_index, d))

                new_table_data = next(parse_table_data(new_table))

                if any(diff(a, b) for a, b in zip_longest(new_table_data, table, fillvalue={})):
                    logger.info("Table is out of sync, rewriting the whole thing")
                    page = header + make_html_table(data, keys=cols) + footer
                    self.update_page(None, old_page['id'], old_page['title'], page, type='page')

                else:
                    logger.info("Table contents identical, no action needed")
        else:
            if new_index is None:
                page = header + make_html_table(data, keys=cols) + footer
            elif isinstance(new_index, list) and len(new_index) == len(data):
                page = header + make_html_table(data, keys=cols, indexer=lambda d: zip(new_index, d))
            else:
                raise ValueError(f"Invalid new_index definition; must "
                                 f"be a list of equal length to the dataset: {new_index} : {data}")
            self.create_page(space, pagename, page, parent_id=None, type='page')
