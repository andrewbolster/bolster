"""Confluence client extension for posting/updating persistent HTML table reports.

Wraps the ``atlassian-python-api`` ``Confluence`` client with
:meth:`Confluence.post_html_report`, which creates a page if it doesn't
exist, or otherwise compares the table already on the page against the new
data (via :mod:`bolster.utils.html_tables`) and only rewrites the page if
the content has actually changed — making it safe to call repeatedly (e.g.
on a schedule) without spamming Confluence's page-history with no-op edits.
"""

import logging
from itertools import zip_longest
from typing import AnyStr

from atlassian import Confluence as Confluence_Orig

from bolster import diff
from bolster.utils.html_tables import iterate_tables, make_html_table

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Confluence(Confluence_Orig):
    """``atlassian.Confluence`` client extended with HTML table report persistence."""

    def post_html_report(
        self,
        space: AnyStr,
        pagename: AnyStr,
        data: list[dict],
        cols: list,
        append: bool = False,
        prepend=False,
        header=None,
        footer=None,
        new_index: list | None = None,
    ):
        """Create or update a Confluence page containing an HTML table report.

        If the page doesn't exist, it's created with the given data. If it
        does exist, the existing table is compared against ``data``: an
        identical table is left untouched (no edit, no new page version);
        a changed table triggers a full rewrite. With ``append``/``prepend``,
        a single new row is added to the existing table instead of
        replacing it (unless that row's index is already present).

        Args:
            space: Confluence space key (or personal space, e.g. ``"~bolster"``).
            pagename: Title of the page to create or update.
            data: List of row dicts to render as the table body.
            cols: Column names/order for the table header.
            append: If True, add ``data`` as a single new row at the end of
                the existing table instead of replacing its contents.
            prepend: If True, add ``data`` as a single new row at the start
                of the existing table instead of replacing its contents.
            header: Optional HTML to insert before the table (default: none).
            footer: Optional HTML to insert after the table (default: none).
            new_index: Index value(s) for ``data``'s row(s) (e.g. when
                appending). Defaults to a list of ``None`` the same length
                as ``data``.

        Raises:
            ValueError: If both ``append`` and ``prepend`` are set, if more
                than one row is given for an append/prepend, or if
                ``new_index`` doesn't match ``data``'s length when creating
                a new page.
            TypeError: If ``new_index`` is provided but isn't a list.
        """
        if header is None:
            header = ""
        if footer is None:
            footer = ""
        if new_index is None:
            new_index = [None for _ in data]

        if append and prepend:
            raise ValueError("Can't have both append and prepend!")

        if not isinstance(new_index, list):
            raise TypeError(f"Got new_index {new_index}, expected a list")

        if self.page_exists(space, pagename):
            self.__update_existing_table_report_page(
                space, pagename, data, cols, prepend, append, header, footer, new_index
            )
        else:
            self.__create_new_table_report_page(space, pagename, data, cols, header, footer, new_index)

    def __create_new_table_report_page(self, space, pagename, data, cols, header, footer, new_index):
        if new_index is None:
            page = header + make_html_table(data, keys=cols) + footer
        elif isinstance(new_index, list) and len(new_index) == len(data):
            page = header + make_html_table(data, keys=cols, indexer=lambda d: zip(new_index, d, strict=False))
        else:
            raise ValueError(
                f"Invalid new_index definition; must be a list of equal length to the dataset: {new_index} : {data}"
            )
        self.create_page(space, pagename, page, parent_id=None, type="page")

    def __update_existing_table_report_page(
        self, space, pagename, data, cols, prepend, append, header, footer, new_index
    ):
        old_page = self.get_page_by_title(space, pagename)
        old_page_body = self.get_page_by_id(old_page["id"], expand="body.storage")["body"]["storage"]["value"]
        logger.info("Page exists")
        table = next(iterate_tables(old_page_body))
        # We know that the None is actually the 'index' column
        # Also we know the column order....
        table_index = [d[None] for d in table]
        table = [
            {
                k: v
                for k, v in sorted(
                    d.items(),
                    key=lambda _d: cols.index(_d[0]) if _d[0] in cols else len(cols),
                )
                if k is not None
            }
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
                new_table = make_html_table(
                    table + data if append else data + table,
                    keys=cols,
                    indexer=lambda d: zip(
                        table_index + new_index if append else new_index + table_index,
                        d,
                        strict=False,
                    ),
                )
                page = header + new_table + footer
                self.update_page(old_page["id"], old_page["title"], page, parent_id=None, type="page")

        else:
            new_table = make_html_table(data, keys=cols, indexer=lambda d: zip(table_index, d, strict=False))

            new_table_data = [
                {k: v for k, v in row.items() if k is not None} for row in next(iterate_tables(new_table))
            ]

            if any(diff(a, b) for a, b in zip_longest(new_table_data, table, fillvalue={})):
                logger.info("Table is out of sync, rewriting the whole thing")
                page = header + make_html_table(data, keys=cols) + footer
                self.update_page(old_page["id"], old_page["title"], page, parent_id=None, type="page")

            else:
                logger.info("Table contents identical, no action needed")
