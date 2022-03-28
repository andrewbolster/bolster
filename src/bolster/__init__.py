# coding=utf-8
"""Top-level package for Bolster."""

__author__ = """Andrew Bolster"""
__email__ = "me@andrewbolster.info"
__version__ = "0.1.2"

import base64
import contextlib
import gzip
import json
import logging
import os
import random
import sys
import time
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from functools import wraps, partial
from itertools import chain, islice, groupby
from operator import itemgetter
from pathlib import Path
from typing import (
    Sequence,
    Generator,
    Iterable,
    List,
    Dict,
    Iterator,
    Union,
    AnyStr,
    Optional,
    Callable,
    SupportsInt,
    SupportsFloat,
    Tuple,
    Set,
    Hashable,
    Any,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _dumb_passthrough(x, **kwargs):
    """Pointless passthrough replacement for tqdm (and similar) fallback

    Args:
      x: return:

    Returns:

    """
    return x


def always(x, **kwargs) -> bool:
    """Pointless passthrough replacement for 'always true' filtering

    >>> always('false')
    True
    >>> always(False)
    True
    >>> always(True)
    True
    """

    return True


def poolmap(
    f: Callable,
    iterable: Iterable,
    max_workers: Optional[int] = None,
    progress: Callable = None,
    **kwargs,
) -> Dict:
    """Helper function to encapsulate a ThreadPoolExecutor mapped function workflow
    Accepts (assumed to be `tqdm` style) progress monitor callback

    `kwargs` are passed identically to all `f(i)` calls for each i in `iterable`

    Args:
      f: function to map across
      iterable:
      max_workers: (Default value = None)
      progress: (Default value = None)
      **kwargs: passed as arguments to f

    Returns:

    """
    futures = {}
    results = {}

    if progress is None:
        progress = _dumb_passthrough

    with ThreadPoolExecutor(max_workers=max_workers) as exc:
        for arg in iterable:
            if arg not in results:
                futures[exc.submit(f, arg, **kwargs)] = arg
        for future in progress(as_completed(futures), total=len(futures)):
            arg = futures[future]
            results[arg] = future.result()

    return results


def batch(seq: Sequence, n: int = 1) -> Generator[Iterable, None, None]:
    """Split a sequence into n-length batches (is still iterable, not list)

    Args:
      seq:
      n:  (Default value = 1)

    Returns:

    >>> next((b for b in batch(range(10), 2)))
    range(0, 2)
    >>> [b for b in batch(list(range(10)), 2)]
    [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9]]
    """
    parent_length = len(seq)
    for ndx in range(0, parent_length, n):
        yield seq[ndx : min(ndx + n, parent_length)]


def chunks(iterable: Iterable, size=10) -> Generator[List, None, None]:
    """Outputs <list> chunks of size N from an iterable (generator)

    Args:
      iterable: param size:
      iterable: Iterable:
      size:  (Default value = 10)

    Returns:

    >>> next((b for b in chunks(range(10), 2)))
    [0, 1]
    >>> [b for b in chunks(list(range(10)), 2)]
    [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9]]
    """

    iterator = iter(iterable)
    for first in iterator:
        yield list(chain([first], islice(iterator, size - 1)))


def arg_exception_logger(func: Callable) -> Callable:
    """Helper Decorator to provide info on the arguments that cause the exception of a wrapped function

    Args:
      func:

    Returns:

    """

    # noinspection PyMissingOrEmptyDocstring
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            raise ValueError(f"Failed with args {args} and kwargs {kwargs}") from e

    return wrapper


# noinspection PyShadowingNames
def backoff(
    exception_to_check: Union[BaseException, Sequence[BaseException]],
    tries: SupportsInt = 5,
    delay: SupportsFloat = 0.2,
    backoff: SupportsFloat = 2,
    logger: Optional[logging.Logger] = logger,
):
    """Retry calling the decorated function using an exponential backoff.

    http://www.saltycrane.com/blog/2009/11/trying-out-retry-decorator-python/
    original from: http://wiki.python.org/moin/PythonDecoratorLibrary#Retry

    Args:
      exception_to_check: the exception to check. may be a tuple of
    exceptions to check
      tries: number of times to try (not retry) before giving up (Default value = 5)
      delay: initial delay between retries in seconds (Default value = 0.4)
      backoff: backoff multiplier e.g. value of 2 will double the delay
    each retry (Default value = 2)
      logger: logger to use. If None, print (Default value = local utils logger)

    Returns:

    """

    # noinspection PyMissingOrEmptyDocstring
    def deco_retry(f):
        # noinspection PyMissingOrEmptyDocstring
        @wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            mdelay += (random.random() - 0.5) * (delay / 2)
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except exception_to_check as e:
                    msg = f"{e}, Retrying in {mdelay} seconds..."
                    if logger:
                        logger.warning(msg)
                    else:
                        print(msg)
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)

        return f_retry  # true decorator

    return deco_retry


class MultipleErrors(BaseException):
    """Exception Class to enable the capturing of multiple exceptions without interrupting control flow, i.e. catch
    the exception, but carry on and report the exceptions at the end.

    E.g.

    .. code-block:: python

        exceptions = MultipleErrors()
        try:
            do_risky_thing_with(this) #raises ValueError
        except:
            exceptions.capture_current_exception()
        try:
            do_other_thing_with(this) #raises AttributeError
        except:
            exceptions.capture_current_exception()
        exceptions.do_raise()



    .. code-block:: none

         Traceback (most recent call last):
            ....
        Value Error

        Traceback (most recent call last):
            ...
        AttributeError

    """

    def __init__(self, errors=None):
        self.errors = errors or []

    @classmethod
    def _traceback_for(cls, exc_info):
        """Formatting!"""
        return "".join(traceback.format_exception(*exc_info))

    def __str__(self):
        tracebacks = "\n\n".join(
            self._traceback_for(exc_info) for exc_info in self.errors
        )
        parts = ("See the following exception tracebacks:", "=" * 78, tracebacks)
        msg = "\n".join(parts)
        return msg

    def capture_current_exception(self):
        """Gathers exception info from the current context and retains it"""
        self.errors.append(sys.exc_info())

    def do_raise(self):
        """Raises itself if it contains any errors"""
        if self.errors:
            raise self


def tag_gen(seq: Iterator[Dict], **kwargs) -> Iterator[Dict]:
    """Generator stream that adds a kwargs to each entry yielded

    The below example shows the creation of an empty dict generator where
    tag_gen is used to insert a new key/value (k=1) in each item on the fly

    >>> all([i['k'] == 1 for i in tag_gen(({} for _ in range(4)), k=1)])
    True

    Args:
      seq: param kwargs:
      seq: Iterator[Dict]:
      **kwargs:

    """
    for item in seq:
        new_item = item
        for k, v in kwargs.items():
            new_item[k] = v
        yield new_item


def exceptional_executor(
    futures: Sequence[Future], exception_handler=None, timeout=None
) -> Iterator:
    """Generator for concurrent.Futures handling

    When an exception is raised in an executing Future, f.result() called on it's own will raise that
    exception in the parent thread, killing execution and causing loss of 'future local' scope.

    Instead, query the future for it's exception state first, and handle that separately, by default
    by logging it as an exception.


    Args:
        futures:
        exception_handler:
        timeout:

    Returns:

    """

    def default_hdl(e: BaseException, f: Future):
        try:
            raise e
        except BaseException:
            logging.exception(f"Caught exception in a future: {f}")

    if exception_handler is None:
        exception_handler = default_hdl

    for f in as_completed(futures, timeout=timeout):
        e = f.exception()
        if e is not None:
            exception_handler(e, f)
        else:
            yield f.result()


@contextlib.contextmanager
def working_directory(path: Union[str, Path]) -> Generator:
    """Contextmanager that changes working directory and returns to previous on exit.

    Args:
      path: Union[str: Path]:

    """
    prev_cwd = Path.cwd()
    os.chdir(str(path))
    try:
        yield
    finally:
        os.chdir(str(prev_cwd.absolute()))


def compress_for_relay(obj: Union[List, Dict]) -> AnyStr:
    """Compress json-serializable object to a gzipped base64 string

    Args:
      obj: return:
      obj: Union[List,Dict]:

    >>> decompress_from_relay(compress_for_relay(['test']))
    ['test']

    >>> decompress_from_relay(compress_for_relay({'test':'test'}))
    {'test': 'test'}

    """
    return base64.b64encode(gzip.compress(json.dumps(obj).encode("utf-8"), 6)).decode()


def decompress_from_relay(msg: AnyStr) -> Union[List, Dict]:
    """Uncompress  gzipped base64 string to a json-serializable object
    ['test']

    Args:
      msg: AnyStr:

    Returns:

    """
    return json.loads(gzip.decompress(base64.b64decode(msg)))


class memoize(object):
    """cache the return value of a method

    This class is meant to be used as a decorator of methods. The return value
    from a given method invocation will be cached on the instance whose method
    was invoked. All arguments passed to a method decorated with memoize must
    be hashable.

    If a memoized method is invoked directly on its class the result will not
    be cached. Instead the method will be invoked like a static method:

    .. code-block:: python

        class Obj(object):
            @memoize
            def add_to(self, arg):
            return self + arg

        Obj.add_to(1) # not enough arguments
        Obj.add_to(1, 2) # returns 3, result is not cached

    Source: http://code.activestate.com/recipes/577452-a-memoize-decorator-for-instance-methods/

    Augmented with cache hit/miss population Counters

    """

    def __init__(self, func):
        self.func = func

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self.func
        return partial(self, obj)

    def __call__(self, *args, **kw):
        obj = args[0]
        try:
            cache = obj.__cache
        except AttributeError:
            cache = obj.__cache = {}
            obj.__hits = Counter()
            obj.__misses = Counter()
        key = (self.func, args[1:], frozenset(kw.items()))
        try:
            res = cache[key]
            obj.__hits[key] += 1
        except KeyError:
            res = cache[key] = self.func(*args, **kw)
            obj.__misses[key] += 1
        return res


def pretty_print_request(
    req, expose_auth=False, authentication_header_blacklist: Optional[Sequence] = None
) -> None:
    """At this point it is completely built and ready
    to be fired; it is "prepared".

    However pay attention at the formatting used in
    this function because it is programmed to be pretty
    printed and may differ from the actual request.

    Args:
      req:
      expose_auth:  (Default value = False)

    Returns:

    """
    printable_headers = {k: v for k, v in req.headers.items()}
    if not expose_auth:
        for header in authentication_header_blacklist:
            if header in printable_headers.keys():
                printable_headers[header] = "<<REDACTED>>"
    print(
        f"-----------START-----------\n" f"{req.method} {req.url}\n",
        "\n".join("{}: {}".format(k, v) for k, v in printable_headers.items()),
    )
    if req.body is not None:
        print(req.body)


def get_recursively(search_dict: Dict, field: str) -> List:
    """Takes a dict with nested lists and dicts,
    and searches all dicts for a key of the field
    provided.

    Originally taken from https://stackoverflow.com/a/20254842

    Args:
      search_dict: Dict:
      field: str:

    Returns:

    >>> get_recursively({'id' : 5,'children' : {'id' : 6,'children' : {'id' : 7,'children' : {}}}}, 'id')
    [5, 6, 7]
    """
    fields_found = []

    for key, value in search_dict.items():

        if key == field:
            fields_found.append(value)

        elif isinstance(value, dict):
            results = get_recursively(value, field)
            for result in results:
                fields_found.append(result)

        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    more_results = get_recursively(item, field)
                    for another_result in more_results:
                        fields_found.append(another_result)

    return fields_found


def transform_(r: Dict, rule_keys: Dict[AnyStr, Optional[Tuple]]) -> Dict:
    """
    Generic Item-wise transformation function;
    The values in `r` are updated based on key-matching in `rule_keys`,
    i.e. -> out[k] = rule_keys[k] (r[k])

    HOWEVER, this can do more that straight callable mapping; can *also* update
    the key, i.e., for a given rule such that `R = rule_keys[k]`:

    R can be used to select that field to be selected in the output
    >>> r = {'a':'1','b':'2','c':'3'}
    >>> transform_(r, {'a':None})
    {'a': '1'}

    Rename a key
    >>> transform_(r, {'a':('A',None)})
    {'A': '1'}

    Apply a function to a key's value
    >>> transform_(r, {'a':('a',int)})
    {'a': 1}

    Or a combination of these
    >>> transform_(r, {'a':('A',int), 'b':None})
    {'A': 1, 'b': '2'}

    """
    out_record = {}
    for k, v in rule_keys.items():
        f = lambda x: x  # noqa: E731

        if v is None:
            new_k = k
        else:
            try:
                new_k, f = v
            except ValueError:
                logger.exception("Rules must have either None value or a 2-tuple")
                raise

            if new_k is None:
                new_k = k
            if f is None:
                f = lambda x: x  # noqa: E731

        out_record[new_k] = f(r[k]) if k in r else None

    return out_record


def diff(new: Dict, old: Dict, excluded_fields: Optional[set] = None) -> Dict:
    """
    Perform a one-depth diff of a pair of dictionaries

    #TODO diff needs tests
    """
    if excluded_fields is None:
        excluded_fields = set()

    diffed_values = {
        k: {"old": old.get(k, None), "new": new.get(k, None)}
        for k in set(new.keys()).union(old.keys()) - excluded_fields
        if old.get(k, None) != new.get(k, None)
    }
    return diffed_values


def aggregate(
    base: List[Dict],
    group_key: Union[AnyStr, Tuple[AnyStr], List[AnyStr]],
    item_key: AnyStr,
    condition: Optional[Callable] = None,
):
    """
    Abstracted groupby-sum for lists of dicts
    operationally equivalent to
    # TODO aggregate needs tests
    ```
    df = pd.DataFrame(base)
    df.where(condition).groupby(group_key)[item_key].sum()
    ```

    Args:
        base:
        group_key:
        item_key:
        condition:

    Returns:

    """
    agg_c = Counter()
    if condition is None:
        condition = lambda x: True  # noqa: E731

    if isinstance(group_key, (tuple, list)):
        grouper = itemgetter(*group_key)
    else:
        grouper = itemgetter(group_key)

    for source_key, g in groupby(filter(condition, base), grouper):
        for sig in g:
            agg_c[source_key] += sig[item_key]
    agg_d = dict(sorted(agg_c.items(), key=itemgetter(1), reverse=True))
    return agg_d


def breadth(d):
    """
    Get the total 'width' of a tree

    > Why was this a thing? No idea

    """
    if isinstance(d, dict):
        width = sum(map(breadth, d.values()))
    else:
        width = 1
    return width


def depth(d: Dict[Any, int]) -> int:
    """
    Get the maximum depth of a tree
    """
    if isinstance(d, dict):
        height = max(map(depth, d.values())) + 1
    else:
        height = 0
    return height


def set_keys(d: Dict) -> Set:
    """
    Extract the set of all keys of a nested dict/tree
    """
    keys = set()
    for k, v in d.items():
        if isinstance(v, dict):
            keys.update(set_keys(v))
        else:
            keys.update([k])
    return keys


def keys_at(d: Dict, n: SupportsInt, i: SupportsInt = 0) -> Iterator:
    """
    Extract the keys of a tree at a given depth
    """
    if isinstance(d, dict):
        for k, v in d.items():
            if i == n:
                yield k
            else:
                yield from keys_at(v, n, i + 1)


def items_at(d: Dict, n: SupportsInt, i: SupportsInt = 0) -> Iterator[Tuple]:
    """
    Extract the elements from a tree at a given depth
    """
    if isinstance(d, dict):
        for k, v in d.items():
            if i == n:
                yield k, v
            else:
                yield from items_at(v, n, i + 1)


def leaves(d: Dict) -> Iterator:
    """
    Iterate on the leaves of a tree
    """
    if isinstance(d, dict):
        for k, v in d.items():
            yield from leaves(v)
    else:
        yield (d)


def leaf_paths(d: Dict, path: Optional[List] = None) -> Iterator[Tuple[List, Dict]]:
    if path is None:
        path = []
    if isinstance(d, dict):
        for k, v in d.items():
            yield from leaf_paths(v, path + [k])
    else:
        yield (path, d)


def flatten_dict(d: Dict, head: str = "", sep: str = ":") -> Dict:
    new_d = {}
    for k, v in d.items():
        if isinstance(v, dict):
            new_d.update(
                flatten_dict(
                    # Sort the inner items first to have alpha order but preserve outer structure
                    dict(sorted(v.items())),
                    head=k,
                )
            )
        else:
            new_d[sep.join([head, k])] = v
    return new_d


def uncollect_object(d: Dict) -> Dict:
    new_d = {}
    for k, v in d.items():
        if isinstance(v, (defaultdict, Counter)):
            new_d[k] = uncollect_object(v)
        else:
            new_d[k] = v
    return new_d


def dict_concat_safe(
    d: Dict, keys: List[Hashable], default: Optional[Any] = None
) -> Iterator:
    """
    Really Lazy Func because `dict.get('key',default)` is a pain in the ass for lists
    """
    for k in keys:
        yield d.get(k, default)


def build_default_mapping_dict_from_keys(keys: List[str]) -> Dict[str, str]:
    """
    Constructs a mapping dictionary between (presumably) snakecase keys to 'human-readable' title case

    Intended for easy construction of presentable graphs/tables etc.

    >>> build_default_mapping_dict_from_keys(['a_b','b_c','c_d'])
    {'a_b': 'A B', 'b_c': 'B C', 'c_d': 'C D'}
    """
    return dict([(f, f.replace("_", " ").title()) for f in keys])
