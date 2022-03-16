from itertools import zip_longest
from typing import Dict

from defusedxml import ElementTree as ET

from .. import breadth
from .. import depth
from .. import items_at
from .. import leaf_paths
from .. import leaves
from .. import nested_defaultdict
from .. import set_keys
from .. import setInDict
from .. import uncollect_object


def table_walker(table_data, row_index=0, col_min=None, col_max=None, debug=True):
    # Map out Colspan-extents first (i.e. width)
    schema = {}
    col_ids = list(table_data[row_index].keys())
    col_widths = [j - i for i, j in zip(col_ids[:-1], col_ids[1:])]
    max_key = max(set_keys(table_data))

    for _id, _w, _head in zip_longest(
        col_ids, col_widths, table_data[row_index].values(), fillvalue=None
    ):

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


def iterate_tables(body):
    table = ET.XML(tag(body=body)).find("table")
    if table is None:
        yield []
    else:
        for _t, t in enumerate(table):
            values = parse_table_data(_t, t)
            yield (values)


def parse_table_data(_t, table):
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
        values = [{k: "" for k in headers}]
    return values
