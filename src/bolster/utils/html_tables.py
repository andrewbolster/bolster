import copy
from collections import defaultdict
from itertools import zip_longest
from typing import Dict

from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET

from .. import breadth
from .. import depth
from .. import items_at
from .. import leaf_paths
from .. import leaves
from .. import set_keys
from .. import setInDict
from .. import uncollect_object


def parse_html_tables_native(html_body):
    tables = []
    tables_html = BeautifulSoup(html_body).find_all("table")

    # Parse each table
    for n in range(0, len(tables_html)):

        n_cols = 0
        n_rows = 0

        for row in tables_html[n].find_all("tr"):
            col_tags = row.find_all(["td", "th"])
            if len(col_tags) > 0:
                n_rows += 1
                if len(col_tags) > n_cols:
                    n_cols = len(col_tags)

        # Create dataframe
        df = defaultdict(dict)

        # Create list to store rowspan values
        skip_index = [0 for i in range(0, n_cols)]

        # Start by iterating over each row in this table...
        row_counter = 0
        for row in tables_html[n].find_all("tr"):

            # Skip row if it's blank
            if len(row.find_all(["td", "th"])) == 0:
                next

            else:

                # Get all cells containing data in this row
                columns = row.find_all(["td", "th"])
                col_dim = []
                row_dim = []
                col_dim_counter = -1
                row_dim_counter = -1
                col_counter = -1
                this_skip_index = copy.deepcopy(skip_index)

                for col in columns:

                    # Determine cell dimensions
                    colspan = col.get("colspan")
                    if colspan is None:
                        col_dim.append(1)
                    else:
                        col_dim.append(int(colspan))
                    col_dim_counter += 1

                    rowspan = col.get("rowspan")
                    if rowspan is None:
                        row_dim.append(1)
                    else:
                        row_dim.append(int(rowspan))
                    row_dim_counter += 1

                    # Adjust column counter
                    if col_counter == -1:
                        col_counter = 0
                    else:
                        col_counter = col_counter + col_dim[col_dim_counter - 1]

                    while skip_index[col_counter] > 0:
                        col_counter += 1

                    # Get cell contents
                    cell_data = col.get_text()

                    # Insert data into cell
                    df[row_counter][col_counter] = cell_data

                    # Record column skipping index
                    if row_dim[row_dim_counter] > 1:
                        this_skip_index[col_counter] = row_dim[row_dim_counter]

            # Adjust row counter
            row_counter += 1

            # Adjust column skipping index
            skip_index = [i - 1 if i > 0 else i for i in this_skip_index]

        # Append dataframe to list of tables
        tables.append(df)

        return tables


def table_walker(table_data, row_index=0, col_min=None, col_max=None, debug=True):
    # Map out Colspan-extents first (i.e. width)
    schema = {}
    col_ids = list(table_data[row_index].keys())
    col_heads = list(table_data[row_index].values())
    col_widths = [j - i for i, j in zip(col_ids[:-1], col_ids[1:])]
    max_key = max(set_keys(table_data))

    for _id, _w, _head in zip_longest(
        col_ids, col_widths, table_data[row_index].values(), fillvalue=None
    ):

        if col_min is not None and _id <= col_min:
            continue
        if col_max is not None and _id > col_max:
            continue

        ## CASES:
        ## Column has no children and is 1 wide
        if _w == 1:
            schema[_head] = []

        ## Column has children; send subset to table_walker row+1 with col bounds
        elif _w is not None:
            schema[_head] = table_walker(
                table_data,
                row_index=row_index + 1,
                col_min=_id - 1,
                col_max=_id + _w - 1,
            )
        ## Column is at the end
        elif _id == max_key:
            schema[_head] = []
        else:
            schema[_head] = table_walker(
                table_data, row_index=row_index + 1, col_min=_id - 1
            )
    if not schema:
        # Last nested column won't know it's own width so will result in an empty schema obj
        schema = []
    return schema


def parse_html_table_data(table_data, index_by="record") -> Dict:
    schema = table_walker(table_data)

    data_start = depth(schema)

    # THIS IS A MASSIVE ABUSE OF PYTHON's MEMORY MODEL!
    for index in table_data.keys():
        if index >= data_start:
            for src, dest in zip(table_data[index].values(), leaves(schema)):
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

        rec_defaultdict = lambda: defaultdict(rec_defaultdict)

        for i in range(height):
            row = defaultdict(rec_defaultdict)

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
        raise ValueError(
            "Invalid value for `index_by`: must be one of 'index'/'record'"
        )
    return result


def cell(attr="", colspan=1, rowspan=1, **kwargs):
    if colspan > 1:
        attr += f' colspan="{colspan}"'
    if rowspan > 1:
        attr += f' rowspan="{rowspan}"'
    return tag(attr, **kwargs)


def tag(attr="", **kwargs):
    out = []
    for tag, txt in kwargs.items():
        out.append(f"<{tag}{attr}>{txt}</{tag}>")
    return "".join(out)


def make_nested_column_html_table_header(n, index=False):
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

    header = "\t\n".join(header_rows)

    return header


def make_html_table(data, keys=None, indexer=enumerate, nested=False, fmt=None):
    if fmt is None:
        fmt = (
            lambda v: f"{v:.2%}"
            if isinstance(v, (int, float)) and v < 1 and v > 0
            else f"{v}"
        )

    if nested:
        header = (
            make_nested_column_html_table_header(
                keys if keys is not None else data[0], index=True
            )
            + "\n"
        )
    else:
        headers = (
            keys if keys is not None else list({k for v in data for k in v.keys()})
        )
        header = tag(tr="".join(tag(th=txt) for txt in [""] + headers)) + "\n"

    rows = "\n".join(
        tag(
            tr="".join(
                tag(' style="font-weight: bold;"', td=i)
                + "".join(tag(td=fmt(v)) for v in leaves(d))
            )
        )
        for i, d in indexer(data)
    )
    table = tag(table="\n" + header + rows + "\n")
    return table


def make_nested_column_table(n):
    header_rows = []
    max_depth = depth(n)

    for i in range(max_depth):
        header = []
        max_depth_this_row = max([depth(v) for k, v in items_at(n, i)])
        for k, v in items_at(n, i):
            header.append(
                cell(
                    th=k, colspan=breadth(v), rowspan=1 + max_depth_this_row - depth(v)
                )
            )
        header_rows.append(tag(tr="\t\t\n".join(header)))

    header = "\t\n".join(header_rows)
    data = tag(tr="".join([tag(td=v) for v in leaves(n)]))

    table = tag(table=header + data)
    return table


def parse_table_data(body):
    table = ET.XML(tag(body=body)).find("table")
    if table is None:
        yield []
    else:
        for _t, t in enumerate(table):
            headers = []
            values = []
            if t.tag == "tbody":
                # Walk tbody
                for r, row in enumerate(t):
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
                for e, element in enumerate(t):
                    if _t == 0:
                        # Assume header
                        headers.append(element.text)
                    else:
                        value[headers[e]] = element.text
                if value:
                    values.append(value)
            if not values and headers:
                values = [{k: "" for k in headers}]
            yield (values)
