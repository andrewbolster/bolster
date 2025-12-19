from typing import AnyStr, BinaryIO, Dict, Union

import pandas as pd


def save_xls(dict_df: Dict[AnyStr, pd.DataFrame], path: Union[str, BinaryIO]) -> None:
    """
    Save a dictionary of dataframes to an excel file, with each dataframe as a separate page
    """

    with pd.ExcelWriter(path) as writer:
        for key in dict_df:
            dict_df[key].to_excel(writer, key)
