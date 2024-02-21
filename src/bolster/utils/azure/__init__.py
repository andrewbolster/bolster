"""
Azure Utils
"""
from urllib.parse import urlparse


def az_file_url_to_query_components(url: str):
    """
    Helper function to parse an Azure file URL into its components to then be used by `pandas`/`dask`/`fsspec` etc.

    >>> az_file_url_to_query_components("https://storageaccount.blob.core.windows.net/container/file_path.parquet")
    {'storage_account': 'storageaccount', 'container': 'container', 'file_path': 'file_path.parquet'}
    """

    p = urlparse(url)
    assert not p.params, f"Invalid Params: {p.params}"
    assert not p.fragment, f"Invalid Fragment: {p.fragment}"
    assert not p.query, f"Invalid Params: {p.query}"

    netlocs = p.netloc.split(".")
    assert len(netlocs) == 5, f"Invalid netlocs: {p.netloc}: Not long enough"
    assert netlocs[2:] == [
        "core",
        "windows",
        "net",
    ], f"Invalid netlocs: {p.netloc} should end in core.windows.net"
    assert netlocs[1] in [
        "blob",
        "dfs",
    ], f"Invalid netlocs: {p.netloc} should be one of blob/dfs"

    storage_account = netlocs[0]
    _, container, *paths = p.path.split(
        "/"
    )  # path starts with a / so p.path.split('/')[0] == ''
    file_path = "/".join(paths)

    return dict(
        storage_account=storage_account, container=container, file_path=file_path
    )
