"""HTML table generation and parsing for Confluence-style storage-format tables.

Generates `<table>` HTML (flat or with nested/grouped column headers using
colspan/rowspan) suitable for posting to Confluence pages, and parses that
same HTML back into structured records — including reconstructing nested
column groupings from a flat position-indexed representation.

Generated tables always wrap rows in `<tbody>` to match Confluence's own
storage-format output, so freshly-generated HTML parses identically to a
page body fetched back from the Confluence API.

Example:
    >>> from bolster.utils.html_tables import make_html_table, iterate_tables
    >>> data = [{"name": "Alice", "score": 92}]
    >>> html = make_html_table(data, keys=["name", "score"])
    >>> rows = next(iterate_tables(html))
    >>> rows[0]["name"]
    'Alice'
"""

from itertools import zip_longest

from defusedxml import ElementTree as ET

from bolster import (
    breadth,
    depth,
    items_at,
    leaf_paths,
    leaves,
    nested_defaultdict,
    set_keys,
    setInDict,
    uncollect_object,
)


def table_walker(table_data, row_index=0, col_min=None, col_max=None, debug=True):
    """Recursively infer a nested column schema from a position-indexed table.

    Walks a table represented as ``{row_index: {col_index: value}}`` and
    reconstructs the colspan-implied grouping structure, starting from the
    header row(s). This is the inverse of the layout produced by
    :func:`make_nested_column_html_table_header`.

    Args:
        table_data: Mapping of row index to a mapping of column index to
            cell value, e.g. ``{0: {0: "", 1: "group_a"}, 1: {...}}``.
        row_index: Header row to start walking from (default: 0).
        col_min: Exclusive lower column-index bound for this recursive call.
        col_max: Inclusive upper column-index bound for this recursive call.
        debug: Unused; retained for signature compatibility.

    Returns:
        A nested mapping from header label to either a deeper schema dict
        (for grouped columns) or an empty list (for leaf columns), or an
        empty list if no columns are found in range.

    Example:
        >>> table_walker({0: {0: "", 1: "name"}, 1: {0: 0, 1: "Alice"}})
        {'': [], 'name': []}
    """
    # Map out Colspan-extents first (i.e. width)
    schema = {}
    col_ids = list(table_data[row_index].keys())
    col_widths = [j - i for i, j in zip(col_ids[:-1], col_ids[1:], strict=False)]
    max_key = max(set_keys(table_data))

    for _id, _w, _head in zip_longest(col_ids, col_widths, table_data[row_index].values(), fillvalue=None):
        if col_min is not None and _id <= col_min:
            continue
        if col_max is not None and _id > col_max:
            continue

        # CASES:
        # Column has no children and is 1 wide
        if _w == 1:
            schema[_head] = []

        # Column has children; send subset to table_walker row+1 with col bounds
        elif _w is not None:
            schema[_head] = table_walker(
                table_data,
                row_index=row_index + 1,
                col_min=_id - 1,
                col_max=_id + _w - 1,
            )
        # Column is at the end
        elif _id == max_key:
            schema[_head] = []
        else:
            schema[_head] = table_walker(table_data, row_index=row_index + 1, col_min=_id - 1)
    if not schema:
        # Last nested column won't know it's own width so will result in an empty schema obj
        schema = []
    return schema


def parse_html_table_data(table_data, index_by="record") -> dict:
    """Reconstruct structured records from a position-indexed nested table.

    Note:
        The header row must include an explicit empty-string (``""``) key
        for the index column, matching the convention used by
        :func:`make_html_table` (``[""] + headers``). Omitting it raises a
        ``KeyError`` rather than a descriptive validation error.

    Args:
        table_data: Mapping of row index to a mapping of column index to
            cell value (see :func:`table_walker`).
        index_by: ``"record"`` (default) returns ``{index_value: {col: val,
            ...}}``; ``"index"`` returns ``{col: [values...]}`` instead.

    Returns:
        A dict keyed by row index (``index_by="record"``) or by column name
        (``index_by="index"``), reconstructing any nested column groupings.

    Raises:
        ValueError: If column data entries have inconsistent heights, or if
            ``index_by`` is not one of ``"index"``/``"record"``.
        KeyError: If the header row is missing the empty-string index key.

    Example:
        >>> table_data = {
        ...     0: {0: "", 1: "name", 2: "score"},
        ...     1: {0: 0, 1: "Alice", 2: 92},
        ... }
        >>> parse_html_table_data(table_data)
        {0: {'name': 'Alice', 'score': 92}}
    """
    schema = table_walker(table_data)

    data_start = depth(schema)

    # THIS IS A MASSIVE ABUSE OF PYTHON's MEMORY MODEL!
    for index in table_data:
        if index >= data_start:
            for src, dest in zip(table_data[index].values(), leaves(schema), strict=False):
                dest.append(src)

    if index_by == "index":
        result = schema
    elif index_by == "record":
        rows = {}

        columns = list(leaf_paths(schema))

        heights = {len(v) for k, v in columns}
        if len(heights) > 1:
            raise ValueError("Column data entries are not the same height!")
        height = max(heights)

        for i in range(height):
            row = nested_defaultdict()

            for path, vals in columns:
                root, *r_path = path
                dest = row[root]
                for k in r_path:
                    dest = dest[k]
                setInDict(row, path, vals[i])
            dt = row.pop("")
            rows[dt] = uncollect_object(row)

        result = rows
    else:
        raise ValueError("Invalid value for `index_by`: must be one of 'index'/'record'")
    return result


def cell(attr="", colspan=1, rowspan=1, **kwargs):
    """Build a single HTML table cell with optional colspan/rowspan attributes.

    Args:
        attr: Extra attribute string to include (e.g. a ``style="..."``
            snippet), appended before colspan/rowspan if present.
        colspan: Column span; only emitted as an attribute when > 1.
        rowspan: Row span; only emitted as an attribute when > 1.
        **kwargs: Passed through to :func:`tag` — exactly one tag-name to
            content mapping, e.g. ``th="Name"`` or ``td=42``.

    Returns:
        The rendered cell as an HTML string.

    Example:
        >>> cell(th="Name")
        '<th>Name</th>'
        >>> cell(th="Group", colspan=2)
        '<th colspan="2">Group</th>'
    """
    if colspan > 1:
        attr += f' colspan="{colspan}"'
    if rowspan > 1:
        attr += f' rowspan="{rowspan}"'
    return tag(attr, **kwargs)


def tag(attr="", **kwargs):
    """Wrap content in an HTML tag.

    Args:
        attr: Raw attribute string to insert after the tag name (e.g.
            ``' style="color:red;"'``), including the leading space.
        **kwargs: Tag-name to content mapping(s), e.g. ``td="value"``. Each
            keyword argument produces one ``<tag>content</tag>`` element;
            multiple kwargs produce multiple sibling elements concatenated.

    Returns:
        The rendered HTML as a string.

    Example:
        >>> tag(td="value")
        '<td>value</td>'
        >>> tag(' style="color:red;"', td="value")
        '<td style="color:red;">value</td>'
    """
    out = []
    for tag, txt in kwargs.items():
        out.append(f"<{tag}{attr}>{txt}</{tag}>")
    return "".join(out)


def make_nested_column_html_table_header(n, index=False):
    """Build multi-row `<tr>` header HTML for grouped/nested columns.

    Each level of nesting in ``n`` produces one header row, with group
    labels spanning their child columns via ``colspan`` and shorter groups
    padded with ``rowspan`` to reach the full header height.

    Args:
        n: A nested mapping describing the column schema, where leaf values
            are empty lists, e.g. ``{"group_a": {"x": [], "y": []}, "group_b":
            {"z": []}}`` for one level of grouping.
        index: If True, prepends a blank corner cell (rowspan'd to the full
            header height) for the row-index column.

    Returns:
        The header rows as HTML `<tr>...</tr>` strings (not wrapped in a
        `<table>` or `<tbody>` — callers such as :func:`make_html_table`
        combine this with the data rows).

    Example:
        >>> from bs4 import BeautifulSoup
        >>> n = {"group_a": {"x": [], "y": []}, "group_b": {"z": []}}
        >>> html = make_nested_column_html_table_header(n, index=True)
        >>> soup = BeautifulSoup(f"<table><tbody>{html}</tbody></table>", "html.parser")
        >>> len(soup.find_all("tr"))
        2
    """
    header_rows = []
    attr = ' style="text-align:center;vertical-align: middle;"'
    max_depth = depth(n)
    for i in range(max_depth):
        header = []
        if index and i == 0:
            header.append(cell(th="", rowspan=max_depth))
        max_depth_this_row = max([depth(v) for k, v in items_at(n, i)])
        for k, v in items_at(n, i):
            height = 1 + max_depth_this_row - depth(v)
            header.append(cell(th=k, attr=attr, colspan=breadth(v), rowspan=height))
        header_rows.append(tag(tr="\t\t\n".join(header)))

    return "\t\n".join(header_rows)


def make_html_table(data, keys=None, indexer=enumerate, nested=False, fmt=None):
    """Build a complete `<table>` (with `<tbody>`) from a list of records.

    Args:
        data: List of dicts, one per row.
        keys: Column names/order. If ``nested`` is True, this should instead
            be a nested schema mapping (see
            :func:`make_nested_column_html_table_header`); if not provided,
            falls back to ``data[0]``. If not nested and ``keys`` is None,
            columns are inferred from the union of all records' keys (in
            unspecified order).
        indexer: Callable that takes ``data`` and yields ``(index, record)``
            pairs; defaults to :func:`enumerate`. Use a custom indexer to
            control the values shown in the leftmost index column.
        nested: If True, render a multi-row grouped header using ``keys`` as
            the nested schema, and flatten each record's nested values via
            ``leaves()`` for the data row.
        fmt: Callable applied to each cell value before rendering. Defaults
            to formatting floats in (0, 1) as percentages and everything
            else via ``str()``.

    Returns:
        The full table as an HTML string, including a `<tbody>` wrapper
        (matching Confluence's own storage-format output) so it round-trips
        correctly through :func:`iterate_tables`.

    Example:
        >>> from bs4 import BeautifulSoup
        >>> html = make_html_table([{"name": "Alice", "score": 92}], keys=["name", "score"])
        >>> soup = BeautifulSoup(html, "html.parser")
        >>> [td.get_text() for td in soup.find("tbody").find_all("tr")[1].find_all("td")]
        ['0', 'Alice', '92']
    """
    if fmt is None:

        def fmt(v):
            return f"{v:.2%}" if isinstance(v, int | float) and 0 < v < 1 else f"{v}"

    if nested:
        header = make_nested_column_html_table_header(keys if keys is not None else data[0], index=True) + "\n"
    else:
        headers = keys if keys is not None else list({k for v in data for k in v})
        header = tag(tr="".join(tag(th=txt) for txt in [""] + headers)) + "\n"

    rows = "\n".join(
        tag(tr="".join(tag(' style="font-weight: bold;"', td=i) + "".join(tag(td=fmt(v)) for v in leaves(d))))
        for i, d in indexer(data)
    )
    # Wrap header + rows in <tbody> to match Confluence's own storage-format
    # output, so freshly-generated HTML parses identically to a round-tripped
    # page body (parse_table_data only handles the <tbody> branch correctly).
    return tag(table="\n" + tag(tbody="\n" + header + rows + "\n") + "\n")


def iterate_tables(body):
    """Find the first `<table>` in an HTML/storage-format body and parse its rows.

    Args:
        body: HTML (or Confluence storage-format) fragment to parse.

    Yields:
        A list of row dicts for the table's child elements (one yield per
        `<tbody>`/direct child of `<table>`); yields ``[]`` if no `<table>`
        element is found in ``body``.

    Example:
        >>> next(iterate_tables("<table><tbody><tr><th></th><th>name</th></tr>"
        ...     "<tr><td>0</td><td>Alice</td></tr></tbody></table>"))
        [{None: '0', 'name': 'Alice'}]
        >>> next(iterate_tables("<p>no table here</p>"))
        []
    """
    table = ET.XML(tag(body=body)).find("table")
    if table is None:
        yield []
    else:
        for _t, t in enumerate(table):
            values = parse_table_data(_t, t)
            yield (values)


def parse_table_data(_t, table):
    """Parse a single `<tbody>` (or bare row) element into a list of row dicts.

    The first row is always treated as the header (its cell text becomes
    the dict keys for subsequent rows). If a table has headers but no data
    rows, a single row of empty-string values is synthesized rather than
    returning an empty list.

    Args:
        _t: Index of this element within its parent `<table>` — used (in
            the non-``tbody`` branch) to decide whether this is the header.
        table: An ``xml.etree.ElementTree`` element, either a `<tbody>`
            (preferred — matches Confluence's storage format) or a single
            row-like element.

    Returns:
        A list of dicts mapping header text to cell text for each data row.

    Example:
        >>> import bolster.utils.html_tables as ht
        >>> from defusedxml import ElementTree as ET
        >>> body = ht.tag(body="<table><tbody><tr><th></th><th>name</th></tr>"
        ...     "<tr><td>0</td><td>Alice</td></tr></tbody></table>")
        >>> tbody = ET.XML(body).find("table").find("tbody")
        >>> parse_table_data(0, tbody)
        [{None: '0', 'name': 'Alice'}]
    """
    headers = []
    values = []
    if table.tag == "tbody":
        # Walk tbody
        for r, row in enumerate(table):
            value = {}
            for e, element in enumerate(row):
                if r == 0:
                    # Assume header
                    # TODO this fails miserably when links are included in the values
                    headers.append(element.text)
                else:
                    value[headers[e]] = element.text
            if value:
                values.append(value)

    else:
        value = {}
        for e, element in enumerate(table):
            # TODO not sure if this works the way it should; _t in this instance is really the 'id' of the table in the
            # body element
            if _t == 0:
                # Assume header
                headers.append(element.text)
            else:
                value[headers[e]] = element.text
        if value:
            values.append(value)
    if not values and headers:
        values = [dict.fromkeys(headers, "")]
    return values
