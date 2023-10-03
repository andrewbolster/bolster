from typing import AnyStr
from typing import BinaryIO
from typing import Dict
from typing import Union

import pandas as pd


def save_xls(dict_df: Dict[AnyStr, pd.DataFrame], path: Union[str, BinaryIO]):
    """
    Save a dictionary of dataframes to an excel file, with each dataframe as a separate page
    """

    with pd.ExcelWriter(path) as writer:
        for key in dict_df:
            dict_df[key].to_excel(writer, key)
