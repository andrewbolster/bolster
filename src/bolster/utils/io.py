from typing import AnyStr
from typing import Dict

import pandas as pd
from pandas._typing import FilePathOrBuffer


def save_xls(dict_df: Dict[AnyStr, pd.DataFrame], path: FilePathOrBuffer):
    """
    Save a dictionary of dataframes to an excel file, with each dataframe as a separate page
    """

    with pd.ExcelWriter(path) as writer:
        for key in dict_df:
            dict_df[key].to_excel(writer, key)
